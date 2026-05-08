"""
智能分块服务 —— Agentic RAG 核心。

支持：
- 文档结构感知分块（章节层级保留）
- 中文语义段落检测（标点、句边界、段落逻辑）
- 表格/图片/代码块保持完整不拆分
- 父子分块（小粒度检索 + 大粒度上下文）
- 小段落智能合并
- 页面号精确追踪
- 根据文档类型自动调整策略
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.services.document_analyzer import DocStructure


@dataclass
class StructuredBlock:
    """文档中的结构化内容块——解析后的最小单元。"""

    block_type: str  # text | table | image | code
    content: str
    page_number: int
    bbox: tuple[float, float, float, float] | None = None
    table_html: str | None = None
    table_data: list[list[str]] | None = None
    image_path: str | None = None
    section_title: str | None = None
    section_path: str | None = None  # 章节层级路径
    # 新增：图片描述（非 OCR，语义理解）
    image_description: str | None = None
    image_caption: str | None = None
    ocr_status: str | None = None  # success | empty | failed | disabled
    ocr_error: str | None = None
    # 新增：表格标题/说明
    table_caption: str | None = None


@dataclass
class ChunkResult:
    """分块结果。"""

    chunk_id: str
    content: str
    chunk_index: int
    page_start: int
    page_end: int
    chunk_type: str  # text | table | image | code
    parent_chunk_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    table_html: str | None = None
    table_data: list[list[str]] | None = None
    image_path: str | None = None
    section_title: str | None = None
    section_path: str | None = None
    ocr_status: str | None = None
    ocr_error: str | None = None
    image_caption: str | None = None
    image_description: str | None = None
    # Agentic RAG 增强
    content_summary: str | None = None  # 分块内容摘要（用于检索增强）
    is_heading: bool = False
    heading_level: int = 0
    doc_category: str | None = None


class ChunkingService:
    """智能分块器 —— 根据文档结构自适应调整策略。"""

    # 中文语义分隔符优先级（粗 → 细）
    _SEPARATORS_SEMANTIC = [
        # L0: Markdown 标题
        "\n## ", "\n### ", "\n#### ", "\n##### ",
        # L1: 中文章节分界
        "\n第[一二三四五六七八九十百千]+[章节篇部]",
        # L2: 段落间距
        "\n\n", "\n\r\n",
        # L3: 中文句群边界（起承转合）
        "。\n", "；\n", "！\n", "？\n",
        # L4: 中文句边界
        "。", "！", "？", "；",
        # L5: 英文句边界
        ". ", "! ", "? ", ".\n",
        # L6: 空格
        "  ", " ",
        # L7: 无分隔符（强制切断）
        "",
    ]

    # 通用递归分隔符（不带中文章节标记的正则）
    _SEPARATORS_STANDARD = [
        "\n## ", "\n### ", "\n#### ",
        "\n\n", "\n",
        "。", "！", "？", "；",
        "  ", " ", ". ", "! ", "? ",
        "",
    ]

    # 中文章节正则分隔符（需 re.split，不能用 str.split）
    _REGEX_SEPARATORS = {
        "\n第[一二三四五六七八九十百千]+[章节篇部]",
    }
    _CHINESE_CHAR_PATTERN = re.compile(r"[一-鿿㐀-䶿]")
    _CHINESE_PUNCT = re.compile(r"[。！？；，、：""''（）【】《》…—　]")
    _HEADING_PATTERN = re.compile(
        r"^(#{1,6}\s+|第[一二三四五六七八九十百千\d]+[章节篇部条]|"
        r"\d+(?:\.\d+)*\s+[A-Z一-鿿]|[（(][一二三四五六七八九十\d]+[）)])",
        re.MULTILINE,
    )
    _CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
    _LIST_PATTERN = re.compile(r"^[\s]*[-*+]\s+|^[\s]*\d+[\.\、]\s+", re.MULTILINE)

    def __init__(
        self,
        child_chunk_size: int = 768,
        child_chunk_overlap: int = 128,
        parent_chunk_size: int = 2000,
        parent_chunk_overlap: int = 200,
        doc_structure: DocStructure | None = None,
    ) -> None:
        # KB 配置优先；doc_structure 仅影响分块策略与 clamp
        base_size = child_chunk_size
        base_overlap = child_chunk_overlap

        if doc_structure is not None:
            if doc_structure.detected_lang == "zh":
                base_size = max(400, min(base_size, 1200))
            elif doc_structure.category.value == "legal":
                base_size = max(base_size, 300)

            self.child_chunk_size = base_size
            self.child_chunk_overlap = base_overlap
            self.use_parent_chunking = doc_structure.use_parent_chunking
            self.merge_small = doc_structure.merge_small_paragraphs
            self.doc_category = doc_structure.category.value
            self._section_paths: dict[int, str] = {}
        else:
            self.child_chunk_size = base_size
            self.child_chunk_overlap = base_overlap
            self.use_parent_chunking = True
            self.merge_small = True
            self.doc_category = "general"

        self.parent_chunk_size = parent_chunk_size
        self.parent_chunk_overlap = parent_chunk_overlap

        # 选择合适的分隔符顺序（中文与 mixed 均用语义分隔符）
        if doc_structure is not None and doc_structure.detected_lang in ("zh", "mixed"):
            self._active_separators = self._SEPARATORS_SEMANTIC
        else:
            self._active_separators = self._SEPARATORS_STANDARD

    def chunk_blocks(
        self, blocks: list[StructuredBlock], _doc_structure: DocStructure | None = None
    ) -> list[ChunkResult]:
        """对结构化块列表进行智能分块。

        策略：
        1. 代码块、表格、图片保持完整不拆分
        2. 文本块：语义段落检测 → 小段落合并 → 父子分块
        3. 保留章节层级路径
        """
        results: list[ChunkResult] = []
        chunk_index = 0

        # 第一步：分类整理
        text_blocks: list[StructuredBlock] = []
        special_blocks: list[StructuredBlock] = []

        for block in blocks:
            if block.block_type in ("table", "image", "code"):
                special_blocks.append(block)
            else:
                text_blocks.append(block)

        # 第二步：仅合并同页文本，保留页码边界
        if not text_blocks:
            merged_stream: list[StructuredBlock] = []
        else:
            merged_stream = self._merge_text_stream(text_blocks)

        # 第三步：检测并标记语义段落边界
        merged_stream = self._detect_semantic_paragraphs(merged_stream)

        # 第四步：小段落合并（如果启用）
        if self.merge_small:
            merged_stream = self._merge_small_stream(merged_stream)

        # 第五步：按页分块，确保 page_start/page_end 与查看页一致
        page_groups: dict[int, list[StructuredBlock]] = {}
        for block in merged_stream:
            page_groups.setdefault(block.page_number, []).append(block)

        for page_num in sorted(page_groups.keys()):
            page_blocks = page_groups[page_num]
            full_text = "\n".join(b.content for b in page_blocks)
            if not full_text.strip():
                continue
            page_start = page_end = page_num
            section = self._best_section(page_blocks)
            section_path = self._best_section_path(page_blocks)

            if self.use_parent_chunking:
                parent_chunks = self._split_text(
                    full_text, self.parent_chunk_size, self.parent_chunk_overlap
                )
                for parent_text in parent_chunks:
                    if not parent_text.strip():
                        continue
                    parent_id = str(uuid.uuid4())
                    summary = self._generate_chunk_summary(parent_text)
                    child_texts = self._split_text(
                        parent_text, self.child_chunk_size, self.child_chunk_overlap
                    )
                    for child_text in child_texts:
                        if not child_text.strip():
                            continue
                        is_heading, heading_level = self._is_heading(child_text)
                        results.append(ChunkResult(
                            chunk_id=str(uuid.uuid4()),
                            content=child_text,
                            chunk_index=chunk_index,
                            page_start=page_start,
                            page_end=page_end,
                            chunk_type="text",
                            parent_chunk_id=parent_id,
                            section_title=section,
                            section_path=section_path,
                            content_summary=summary,
                            is_heading=is_heading,
                            heading_level=heading_level,
                            doc_category=self.doc_category,
                        ))
                        chunk_index += 1
            else:
                child_texts = self._split_text(
                    full_text, self.child_chunk_size, self.child_chunk_overlap
                )
                for child_text in child_texts:
                    if not child_text.strip():
                        continue
                    is_heading, heading_level = self._is_heading(child_text)
                    results.append(ChunkResult(
                        chunk_id=str(uuid.uuid4()),
                        content=child_text,
                        chunk_index=chunk_index,
                        page_start=page_start,
                        page_end=page_end,
                        chunk_type="text",
                        section_title=section,
                        section_path=section_path,
                        is_heading=is_heading,
                        heading_level=heading_level,
                        doc_category=self.doc_category,
                    ))
                    chunk_index += 1

        # 第六步：特殊块处理
        for block in special_blocks:
            chunk_id = str(uuid.uuid4())
            summary = self._generate_chunk_summary(block.content)

            results.append(ChunkResult(
                chunk_id=chunk_id,
                content=self._enrich_special_content(block),
                chunk_index=chunk_index,
                page_start=block.page_number,
                page_end=block.page_number,
                chunk_type=block.block_type,
                parent_chunk_id=chunk_id,
                bbox=block.bbox,
                table_html=block.table_html,
                table_data=block.table_data,
                image_path=block.image_path,
                section_title=block.section_title or self._best_section([block]),
                section_path=block.section_path,
                ocr_status=block.ocr_status,
                ocr_error=block.ocr_error,
                image_caption=block.image_caption,
                image_description=block.image_description,
                content_summary=summary,
                doc_category=self.doc_category,
            ))
            chunk_index += 1

        logger.info(
            f"分块完成: 总数={len(results)}, "
            f"文本={sum(1 for c in results if c.chunk_type == 'text')}, "
            f"表格={sum(1 for c in results if c.chunk_type == 'table')}, "
            f"图片={sum(1 for c in results if c.chunk_type == 'image')}, "
            f"代码={sum(1 for c in results if c.chunk_type == 'code')}, "
            f"父块={len({c.parent_chunk_id for c in results if c.parent_chunk_id})}"
        )
        return results

    # ---- Semantic paragraph detection ----

    def _detect_semantic_paragraphs(
        self, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """语义段落检测：分析文本的逻辑结构，在语义边界处拆分/合并。"""
        if len(blocks) <= 1:
            return blocks

        result: list[StructuredBlock] = []
        for block in blocks:
            content = block.content
            if not content.strip():
                continue

            # 检测内容是否包含多个语义段落
            # 中文语义边界：标点换行、转折词、总结词
            semantic_splits = self._find_semantic_boundaries(content)
            if len(semantic_splits) <= 1:
                result.append(block)
                continue

            # 在语义边界处拆分为多个 block
            for i, segment in enumerate(semantic_splits):
                if not segment.strip():
                    continue
                result.append(StructuredBlock(
                    block_type="text",
                    content=segment,
                    page_number=block.page_number,
                    bbox=block.bbox,
                    section_title=block.section_title if i == 0 else None,
                    section_path=block.section_path if i == 0 else None,
                ))

        return result

    def _find_semantic_boundaries(self, text: str) -> list[str]:
        """找到文本中的语义边界位置并拆分。

        识别以下边界：
        - 转折词：但是/然而/不过/另一方面
        - 总结词：总之/综上所述/总而言之
        - 举例词：例如/比如/具体来说
        - 递进词：此外/另外/不仅如此
        - 因果词：因此/所以/因而
        - 时间/顺序：首先/其次/然后/最后/第一步/第二步
        """
        boundary_patterns = [
            # 中文转折/递进词（前面至少有一个句号结尾的句子）
            r"(?<=[。！？])\s*(?=但是|然而|不过|尽管如此|另一方面|相反)",
            r"(?<=[。！？])\s*(?=此外|另外|不仅如此|同时|而且|并且)",
            # 总结/结论
            r"(?<=[。！？])\s*(?=总之|综上所述|总而言之|由此|因此|所以|因而)",
            # 顺序/列举
            r"(?<=[。！？])\s*(?=首先|其次|然后|最后|第一步|第二步|第三步|第[一二三四五六七八九十]|\d+[\.\、])",
            # 举例
            r"(?<=[。！？])\s*(?=例如|比如|譬如|具体来说|举例而言)",
            # 英文过渡词
            r"(?<=[.!?]\s)(?=However|Nevertheless|Moreover|Furthermore|Therefore|In conclusion|Additionally|In contrast|On the other hand)",
        ]

        segments = [text]
        for pattern in boundary_patterns:
            new_segments: list[str] = []
            for segment in segments:
                parts = re.split(pattern, segment)
                new_segments.extend(parts)
            segments = new_segments

        # 过滤过短的段落（<20 有效字符），合并回前一段
        merged: list[str] = []
        for seg in segments:
            if merged and self._char_count(seg.strip()) < 20:
                merged[-1] = merged[-1].rstrip() + seg.lstrip()
            elif seg.strip():
                merged.append(seg)

        return merged

    def _merge_text_stream(self, blocks: list[StructuredBlock]) -> list[StructuredBlock]:
        """合并连续文本块；跨页时若前块未句末结束且后块非标题则合并。"""
        sorted_blocks = sorted(blocks, key=lambda b: (b.page_number, id(b)))
        if not sorted_blocks:
            return []
        merged: list[StructuredBlock] = [sorted_blocks[0]]
        for block in sorted_blocks[1:]:
            prev = merged[-1]
            can_merge_same_page = block.page_number == prev.page_number
            can_merge_cross_page = (
                block.page_number == prev.page_number + 1
                and prev.content.rstrip()
                and prev.content.rstrip()[-1] not in "。！？；.!?"
                and not self._is_heading(block.content.strip())[0]
            )
            if can_merge_same_page or can_merge_cross_page:
                merged[-1] = StructuredBlock(
                    block_type="text",
                    content=prev.content + "\n" + block.content,
                    page_number=prev.page_number,
                    bbox=prev.bbox,
                    section_title=prev.section_title or block.section_title,
                    section_path=prev.section_path or block.section_path,
                )
            else:
                merged.append(block)
        return merged

    def _merge_small_stream(self, blocks: list[StructuredBlock]) -> list[StructuredBlock]:
        """文档流式小段落合并。"""
        page_map: dict[int, list[StructuredBlock]] = {}
        for block in blocks:
            page_map.setdefault(block.page_number, []).append(block)
        result: list[StructuredBlock] = []
        for page_num in sorted(page_map.keys()):
            result.extend(self._merge_small_paragraphs({page_num: page_map[page_num]}).get(page_num, []))
        return result

    def _merge_small_paragraphs(
        self, page_texts: dict[int, list[StructuredBlock]]
    ) -> dict[int, list[StructuredBlock]]:
        """合并过小的段落，保持 chunk 语义完整性。"""
        result: dict[int, list[StructuredBlock]] = {}
        min_size = 50

        for page_num, blocks in page_texts.items():
            merged: list[StructuredBlock] = []
            buffer: list[StructuredBlock] = []

            for block in blocks:
                block_len = self._char_count(block.content)
                if block_len < min_size and buffer:
                    buffer.append(block)
                    combined_len = sum(self._char_count(b.content) for b in buffer)
                    if combined_len >= min_size:
                        merged.append(self._fuse_blocks(buffer))
                        buffer = []
                elif block_len < min_size and not buffer:
                    buffer.append(block)
                else:
                    if buffer:
                        merged.append(self._fuse_blocks(buffer))
                        buffer = []
                    merged.append(block)

            if buffer:
                merged.append(self._fuse_blocks(buffer))

            result[page_num] = merged

        return result

    def _fuse_blocks(self, blocks: list[StructuredBlock]) -> StructuredBlock:
        """融合多个连续文本块为一个。"""
        if len(blocks) == 1:
            return blocks[0]
        fused_content = "\n".join(b.content for b in blocks)
        return StructuredBlock(
            block_type="text",
            content=fused_content,
            page_number=blocks[0].page_number,
            bbox=blocks[0].bbox,
            section_title=blocks[0].section_title,
            section_path=blocks[0].section_path,
        )

    _SPECIAL_CONTENT_MAX_CHARS = 1800  # 留空间给 _build_embed_text 添加的元数据头

    @classmethod
    def _truncate_content_for_embed(cls, content: str) -> str:
        """截断过长内容，保证嵌入时加上元数据头后不超出模型上限。"""
        if len(content) <= cls._SPECIAL_CONTENT_MAX_CHARS:
            return content
        truncated = content[:cls._SPECIAL_CONTENT_MAX_CHARS]
        # 尝试在句末/段末截断
        for sep in ("\n\n", "。", ". ", "\n", " "):
            idx = truncated.rfind(sep)
            if idx > cls._SPECIAL_CONTENT_MAX_CHARS // 2:
                return truncated[: idx + len(sep)] + f"\n... (内容已截断，共 {len(content)} 字符)"
        return truncated + f"... (内容已截断，共 {len(content)} 字符)"

    def _enrich_special_content(self, block: StructuredBlock) -> str:
        """为特殊块（表格/图片/代码）生成增强的内容描述，便于向量检索。"""
        parts: list[str] = []

        if block.block_type == "table":
            if block.table_caption:
                parts.append(f"[表格标题] {block.table_caption}")
            if block.section_title:
                parts.append(f"[所在章节] {block.section_title}")
            parts.append(f"[表格内容]\n{self._truncate_content_for_embed(block.content)}")

        elif block.block_type == "image":
            if block.image_caption:
                parts.append(f"[图片说明] {block.image_caption}")
            if block.image_description:
                parts.append(f"[图片描述] {block.image_description}")
            if block.content and block.content != "[图片]" and "OCR" not in block.content:
                parts.append(f"[图片文字] {self._truncate_content_for_embed(block.content)}")
            elif block.content and "OCR" in block.content:
                parts.append(self._truncate_content_for_embed(block.content))

        elif block.block_type == "code":
            parts.append(self._truncate_content_for_embed(block.content))
            functions = re.findall(r"(?:def|class|function|const|let|var)\s+(\w+)", block.content)
            if functions:
                parts.append(f"[代码符号] {', '.join(functions)}")

        else:
            parts.append(self._truncate_content_for_embed(block.content))

        return "\n".join(parts)

    # ---- Text splitting ----

    def _split_text(
        self, text: str, chunk_size: int, chunk_overlap: int
    ) -> list[str]:
        """递归语义分割。"""
        return self._recursive_split(text, list(self._active_separators), chunk_size, chunk_overlap)

    def _recursive_split(
        self, text: str, separators: list[str], chunk_size: int, chunk_overlap: int
    ) -> list[str]:
        """递归文本分割——优先使用高层次分隔符。"""
        if not text.strip():
            return []

        if self._char_count(text) <= chunk_size:
            return [text]

        separator = separators[0] if separators else ""

        if not separator:
            return self._force_split(text, chunk_size, chunk_overlap)

        # 中文章节正则类分隔符
        if separator in self._REGEX_SEPARATORS or separator.startswith("\n第"):
            splits = re.split(r"(?=\n第[一二三四五六七八九十百千]+[章节篇部])", text)
            if splits and not splits[0].strip():
                splits = splits[1:]
        else:
            splits = text.split(separator)

        # 合并过小的片段
        chunks: list[str] = []
        current = ""
        for part in splits:
            test = current + (separator if current and separator else "") + part
            if self._char_count(test) > chunk_size and current:
                chunks.append(current)
                current = part
            else:
                current = test
        if current:
            chunks.append(current)

        # 递归处理过大的 chunk
        remaining_separators = separators[1:] if len(separators) > 1 else []
        if not remaining_separators:
            final: list[str] = []
            for chunk in chunks:
                if self._char_count(chunk) > chunk_size:
                    final.extend(self._force_split(chunk, chunk_size, chunk_overlap))
                else:
                    final.append(chunk)
            return final

        final: list[str] = []
        for chunk in chunks:
            if self._char_count(chunk) > chunk_size:
                final.extend(
                    self._recursive_split(
                        chunk, remaining_separators, chunk_size, chunk_overlap
                    )
                )
            else:
                final.append(chunk)
        return self._apply_overlap(final, chunk_overlap)

    def _advance_by_char_count(self, text: str, start: int, max_count: int) -> int:
        """从 start 起找到使有效字符数不超过 max_count 的最大结束索引。"""
        if start >= len(text) or max_count <= 0:
            return min(start + 1, len(text))
        low, high = start + 1, len(text)
        best = start + 1
        while low <= high:
            mid = (low + high) // 2
            if self._char_count(text[start:mid]) <= max_count:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        return best

    def _tail_by_char_count(self, text: str, max_count: int) -> str:
        """取文本末尾有效字符数不超过 max_count 的子串。"""
        if max_count <= 0 or not text:
            return ""
        for i in range(len(text)):
            tail = text[i:]
            if self._char_count(tail) <= max_count:
                return tail
        return text

    def _force_split(
        self, text: str, chunk_size: int, chunk_overlap: int
    ) -> list[str]:
        """强制按有效字符数切割（带重叠），优先在标点处切断。"""
        chunks: list[str] = []
        start = 0
        text_len = len(text)
        step_count = max(chunk_size - chunk_overlap, 1)

        while start < text_len:
            end = self._advance_by_char_count(text, start, chunk_size)

            if end < text_len:
                lookback_start = max(start, end - 100)
                for i in range(end, lookback_start, -1):
                    if text[i - 1] in "。！？；\n":
                        end = i
                        break

            chunks.append(text[start:end])
            if end >= text_len:
                break
            next_start = self._advance_by_char_count(text, start, step_count)
            start = next_start if next_start > start else min(start + 1, text_len)

        return self._apply_overlap(chunks, chunk_overlap)

    def _apply_overlap(self, chunks: list[str], chunk_overlap: int) -> list[str]:
        """为相邻 chunk 添加重叠窗口，避免语义在边界处断裂。"""
        if chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        result: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            overlap_text = self._tail_by_char_count(prev, chunk_overlap)
            result.append(overlap_text + chunks[i])
        return result

    def _char_count(self, text: str) -> int:
        """计算文本的有效字符数（中文按 1，英文按 1/4）。"""
        chinese_chars = len(self._CHINESE_CHAR_PATTERN.findall(text))
        other_chars = len(text) - chinese_chars
        return chinese_chars + max(other_chars // 4, 1)

    # ---- Heading detection ----

    def _is_heading(self, text: str) -> tuple[bool, int]:
        """检测文本是否为标题/章节开头。"""
        m = self._HEADING_PATTERN.match(text.strip())
        if not m:
            return False, 0

        matched = m.group()
        if matched.startswith("#"):
            level = len(matched) - len(matched.lstrip("#"))
        elif matched.startswith("第"):
            level = 1
        elif re.match(r"^\d+(?:\.\d+)+\s", matched):
            level = len(matched.strip().split("."))
        else:
            level = 1

        return True, min(level, 6)

    def _best_section(self, blocks: list[StructuredBlock]) -> str | None:
        """从块列表中获取最佳章节标题。"""
        for block in blocks:
            if block.section_title:
                return block.section_title
        return None

    def _best_section_path(self, blocks: list[StructuredBlock]) -> str | None:
        """从块列表中获取章节层级路径。"""
        for block in blocks:
            if block.section_path:
                return block.section_path
        return None

    def _generate_chunk_summary(self, text: str, max_len: int = 120) -> str | None:
        """为分块生成简短摘要（基于关键词提取，不依赖 LLM）。

        用于增强检索的相关性判断，在 embedding 之外提供额外的语义信号。
        """
        if len(text) < 100:
            return None

        # 提取前几句作为摘要
        sentences = re.split(r"[。！？.!?\n]", text)
        summary_parts: list[str] = []
        current_len = 0
        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            if current_len + len(s) > max_len:
                break
            summary_parts.append(s)
            current_len += len(s)

        if not summary_parts:
            return None
        return "。".join(summary_parts) + "。"

    def get_expanded_context(
        self,
        chunk: ChunkResult,
        all_chunks: list[ChunkResult],
        context_pages: int = 1,
    ) -> tuple[str | None, str | None]:
        """获取 chunk 的上下文（前后相邻 chunk）。"""
        same_page = [
            c for c in all_chunks
            if c.chunk_type == "text"
            and c.page_start >= chunk.page_start - context_pages
            and c.page_end <= chunk.page_end + context_pages
            and c.chunk_id != chunk.chunk_id
        ]
        same_page.sort(key=lambda c: c.chunk_index)

        idx = chunk.chunk_index
        before = [c for c in same_page if c.chunk_index < idx]
        after = [c for c in same_page if c.chunk_index > idx]

        context_before = "\n".join(c.content for c in before[-2:]) if before else None
        context_after = "\n".join(c.content for c in after[:2]) if after else None
        return context_before, context_after
