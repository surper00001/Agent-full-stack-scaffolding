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
from typing import TYPE_CHECKING

from loguru import logger

from src.services.chunking.data_models import ChunkResult, StructuredBlock  # 向后兼容重导出
from src.services.reference_extractor import ReferenceExtractor

# ── 向后兼容：外部模块从 chunking_service 导入这两个类 ──
__all__ = ["ChunkingService", "ChunkResult", "StructuredBlock"]

if TYPE_CHECKING:
    from src.services.document_analyzer import DocStructure


class ChunkingService:
    """智能分块器 —— 根据文档结构自适应调整策略。"""

    # ── 动态分隔符策略 — 委托给独立配置模块 ──
    from src.services.chunking.separator_strategies import (
        CATEGORY_SEPARATORS as _CATEGORY_SEPARATORS,
    )
    from src.services.chunking.separator_strategies import (
        CHINESE_CHAR_PATTERN as _CHINESE_CHAR_PATTERN,
    )
    from src.services.chunking.separator_strategies import (
        CHINESE_PUNCT as _CHINESE_PUNCT,
    )
    from src.services.chunking.separator_strategies import (
        CODE_BLOCK_PATTERN as _CODE_BLOCK_PATTERN,
    )
    from src.services.chunking.separator_strategies import (
        HEADING_PATTERN as _HEADING_PATTERN,
    )
    from src.services.chunking.separator_strategies import (
        LIST_PATTERN as _LIST_PATTERN,
    )
    from src.services.chunking.separator_strategies import (
        REGEX_SEPARATORS as _REGEX_SEPARATORS,
    )
    from src.services.chunking.separator_strategies import (
        SEPARATORS_ACADEMIC as _SEPARATORS_ACADEMIC,
    )
    from src.services.chunking.separator_strategies import (
        SEPARATORS_LEGAL as _SEPARATORS_LEGAL,
    )
    from src.services.chunking.separator_strategies import (
        SEPARATORS_REPORT as _SEPARATORS_REPORT,
    )
    from src.services.chunking.separator_strategies import (
        SEPARATORS_SEMANTIC as _SEPARATORS_SEMANTIC,
    )
    from src.services.chunking.separator_strategies import (
        SEPARATORS_STANDARD as _SEPARATORS_STANDARD,
    )
    from src.services.chunking.separator_strategies import (
        SEPARATORS_TECHNICAL as _SEPARATORS_TECHNICAL,
    )

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

        # 动态分隔符策略：文档类型 → 语言 → 通用降级
        category_seps = self._CATEGORY_SEPARATORS.get(self.doc_category)
        if category_seps:
            self._active_separators = category_seps
        elif doc_structure is not None and doc_structure.detected_lang in ("zh", "mixed"):
            self._active_separators = self._SEPARATORS_SEMANTIC
        else:
            self._active_separators = self._SEPARATORS_STANDARD

        logger.debug(
            f"分块策略: category={self.doc_category} "
            f"chunk_size={self.child_chunk_size} "
            f"parent={self.use_parent_chunking} "
            f"merge_small={self.merge_small}"
        )

    def chunk_blocks(
        self, blocks: list[StructuredBlock], _doc_structure: DocStructure | None = None
    ) -> list[ChunkResult]:
        """对结构化块进行语义分块。

        策略（分层降级）：
        1. 特殊块（表格/图片/代码）保持完整不拆分
        2. 文本按 section 分组 → 同 section 内按页 → 按 char 分块
        3. 无 section 信息时降级为按页分块
        4. 保留章节层级路径 + 版面标签
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

        # 第二步：合并连续文本流（跨页未完成句合并）
        merged_stream = self._merge_text_stream(text_blocks) if text_blocks else []

        # 第三步：按 section 分组（核心语义边界）
        section_groups = self._group_by_section(merged_stream)

        # 第四步：逐 section 分块
        for _section_key, section_blocks in section_groups:
            section_title = section_blocks[0].section_title if section_blocks else None
            section_path = section_blocks[0].section_path if section_blocks else None

            # 参考文献分组：多层检测确保不遗漏
            # 方式1: _group_by_section 归一化后的 __REFERENCES__ key
            # 方式2: section_title 本身匹配参考文献关键词（兜底）
            # 方式3: 块内首个块的 layout_tag 为 reference（兜底）
            is_reference_section = (
                _section_key == "__REFERENCES__"
                or ReferenceExtractor.is_reference_section(section_title or "")
                or (
                    section_blocks
                    and section_blocks[0].layout_tag == "reference"
                )
            )
            if is_reference_section and not section_title:
                section_title = "参考文献"

            # 参考文献逐条提取：使用 ReferenceExtractor 解析为结构化条目
            if is_reference_section:
                # 滤除标题/章节头块，仅保留实际参考文献内容
                ref_blocks = [
                    b for b in section_blocks
                    if b.layout_tag not in ("heading", "title", "subtitle")
                ]
                if not ref_blocks:
                    continue

                # 按页分组，逐页提取引用条目 —— 保证每条的 page_start 正确
                # （之前全量合并后 min(page) 统一赋值，导致跨页引用全堆在第一页）
                ref_by_page: dict[int, list[StructuredBlock]] = {}
                for b in ref_blocks:
                    ref_by_page.setdefault(b.page_number, []).append(b)

                total_extracted = 0
                for page_num in sorted(ref_by_page.keys()):
                    page_ref_blocks = ref_by_page[page_num]
                    page_ref_text = "\n".join(b.content for b in page_ref_blocks)
                    page_entries = ReferenceExtractor.extract_entries(page_ref_text)

                    if not page_entries:
                        continue

                    for entry in page_entries:
                        embed_parts = [f"[参考文献 {entry.ref_id}]"]
                        if entry.authors:
                            embed_parts.append(f"作者: {entry.authors}")
                        if entry.title:
                            embed_parts.append(f"标题: {entry.title}")
                        if entry.year:
                            embed_parts.append(f"年份: {entry.year}")
                        embed_parts.append(entry.raw_text)
                        embed_content = "\n".join(embed_parts)

                        results.append(ChunkResult(
                            chunk_id=str(uuid.uuid4()),
                            content=embed_content,
                            chunk_index=chunk_index,
                            page_start=page_num,
                            page_end=page_num,
                            chunk_type="reference",
                            section_title=section_title,
                            section_path=section_path,
                            title=entry.title or entry.short_citation,
                            doc_category=self.doc_category,
                            layout_tag="reference",
                        ))
                        chunk_index += 1
                        total_extracted += 1

                if total_extracted > 0:
                    page_start = min(ref_by_page.keys())
                    page_end = max(ref_by_page.keys())
                    logger.info(
                        f"参考文献提取: {total_extracted} 条, "
                        f"pages={page_start}-{page_end}"
                    )
                else:
                    # 兜底：逐页都没拆出来 → 全文回退，不丢弃
                    ref_text = "\n".join(b.content for b in ref_blocks)
                    logger.warning(
                        f"参考文献逐条提取失败（{len(ref_text)}字符），回退为全文分块，"
                        f"pages={min(ref_by_page.keys())}-{max(ref_by_page.keys())}"
                    )
                    section_blocks = ref_blocks
                    # 不 continue，走常规分块流程

            # 小段落合并
            if self.merge_small:
                section_blocks = self._merge_small_paragraphs(
                    {section_blocks[0].page_number: section_blocks}
                ).get(section_blocks[0].page_number, section_blocks)

            # 按页分组（保留页码精确性）
            page_groups: dict[int, list[StructuredBlock]] = {}
            for block in section_blocks:
                page_groups.setdefault(block.page_number, []).append(block)

            for page_num in sorted(page_groups.keys()):
                page_blocks = page_groups[page_num]
                full_text = "\n".join(b.content for b in page_blocks)
                if not full_text.strip():
                    continue
                page_start = page_end = page_num
                # section 信息优先使用 group 级别的
                sec = section_title or self._best_section(page_blocks)
                sec_path = section_path or self._best_section_path(page_blocks)

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
                                section_title=sec,
                                section_path=sec_path,
                                title=sec,
                                content_summary=summary,
                                is_heading=is_heading,
                                heading_level=heading_level,
                                doc_category=self.doc_category,
                                layout_tag=page_blocks[0].layout_tag if page_blocks else None,
                                list_level=page_blocks[0].list_level if page_blocks else 0,
                                list_type=page_blocks[0].list_type if page_blocks else "",
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
                            section_title=sec,
                            section_path=sec_path,
                            title=sec,
                            is_heading=is_heading,
                            heading_level=heading_level,
                            doc_category=self.doc_category,
                            layout_tag=page_blocks[0].layout_tag if page_blocks else None,
                            list_level=page_blocks[0].list_level if page_blocks else 0,
                            list_type=page_blocks[0].list_type if page_blocks else "",
                        ))
                        chunk_index += 1

        # 第五步：特殊块关联到所在 section
        for block in special_blocks:
            chunk_id = str(uuid.uuid4())
            summary = self._generate_chunk_summary(block.content)
            # 找到最近的同 section 文本块
            section = block.section_title or self._best_section([block])
            section_path = block.section_path

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
                section_title=section,
                section_path=section_path,
                title=block.table_caption or block.image_caption or section,
                ocr_status=block.ocr_status,
                ocr_error=block.ocr_error,
                image_caption=block.image_caption,
                image_description=block.image_description,
                table_caption=block.table_caption,
                content_summary=summary,
                doc_category=self.doc_category,
                layout_tag=block.layout_tag,
                image_width=block.image_width,
                image_height=block.image_height,
                list_level=block.list_level,
                list_type=block.list_type,
            ))
            chunk_index += 1

        # 第六步：硬截断 —— 确保所有 chunk 内容不超出 embedding 模型安全上限
        for chunk in results:
            chunk.content = self._hard_cap_content(chunk.content)

        # 第七步：后处理 —— 为文本块关联同页表格/图片（metadata-aware retrieval）
        page_table_info: dict[int, list[tuple[str, str]]] = {}  # page -> [(chunk_id, caption)]
        page_image_info: dict[int, list[tuple[str, str]]] = {}  # page -> [(chunk_id, caption)]
        for chunk in results:
            if chunk.chunk_type == "table":
                caption = chunk.table_caption or chunk.section_title or ""
                page_table_info.setdefault(chunk.page_start, []).append((chunk.chunk_id, caption))
            elif chunk.chunk_type == "image":
                caption = chunk.image_caption or chunk.image_description or chunk.section_title or ""
                page_image_info.setdefault(chunk.page_start, []).append((chunk.chunk_id, caption))

        for chunk in results:
            if chunk.chunk_type == "text":
                tables = page_table_info.get(chunk.page_start)
                images = page_image_info.get(chunk.page_start)
                if tables:
                    chunk.table_refs = [t[0] for t in tables]
                if images:
                    chunk.image_refs = [i[0] for i in images]

        logger.info(
            f"分块完成: 总数={len(results)}, "
            f"文本={sum(1 for c in results if c.chunk_type == 'text')}, "
            f"表格={sum(1 for c in results if c.chunk_type == 'table')}, "
            f"图片={sum(1 for c in results if c.chunk_type == 'image')}, "
            f"代码={sum(1 for c in results if c.chunk_type == 'code')}, "
            f"父块={len({c.parent_chunk_id for c in results if c.parent_chunk_id})}"
        )
        return results

    # ---- Section grouping ----

    # 内容级别的参考文献检测模式（兜底：当 layout_tag 和 section_title 都缺失时使用）
    # 注意：避免使用 \b 词边界（中英文混排时 \b 行为不稳定），改用前瞻/后顾字符类
    _REF_CONTENT_PATTERNS = re.compile(
        r"^\[\d+\]\s|"                          # [1] 编号开头
        r"DOI[：:\s]|doi\.org/|10\.\d{4,}/|"    # DOI
        r"Vol\.\s*\d+|pp\.\s*\d+|No\.\s*\d+|"    # 卷期号
        r"\[J\]\.|J\.[\s\d]|Journal\s+of|"       # 期刊标记（含中文 [J]. 格式）
        r"硕士学位论文|博士学位论文|arXiv|PMID|"      # 中文学位论文
        r"(?:^|\s|,|，|。|;)(?:19|20)\d{2}(?:$|\s|,|，|。|;|\)|\])",  # 年份（不用 \b，用显式前后字符类）
        re.MULTILINE | re.IGNORECASE,
    )

    @classmethod
    def _looks_like_references(cls, text: str) -> bool:
        """内容级别的参考文献检测：不依赖 layout_tag，直接分析文本特征。

        当 PDF 解析器未能正确标记参考文献时，此方法作为最终兜底。
        检测标准：
        - 至少包含 2 个参考文献特征模式（DOI/年份/编号/卷期号等）
        - 文本长度 > 80 字符（排除误判短文本）
        """
        if not text or len(text) < 50:
            return False
        matches = len(cls._REF_CONTENT_PATTERNS.findall(text))
        return matches >= 2

    @staticmethod
    def _group_by_section(
        blocks: list[StructuredBlock],
    ) -> list[tuple[str, list[StructuredBlock]]]:
        """按 section 边界分组文本块，保持文档语义结构。

        降级策略：
        1. 有 section_title 变化 → 新 section 组
        2. 遇到 heading/reference layout_tag → 新 section 组
        3. 内容级参考文献特征检测 → __REFERENCES__ 组（最终兜底）
        4. 无任何 section 信息 → 全部归入一组（降级为全文档）

        特殊处理：参考文献（reference）块单独成组，不与正文混排。
        """
        if not blocks:
            return []

        groups: list[tuple[str, list[StructuredBlock]]] = []
        current_key = ""
        current_blocks: list[StructuredBlock] = []

        for block in blocks:
            section_title = block.section_title or ""
            layout_tag = block.layout_tag or ""

            # heading/title 标签触发新 section
            is_heading_block = layout_tag in ("title", "heading", "subtitle",)
            # reference 标签触发新 section（参考文献独立分组）
            is_reference_block = layout_tag == "reference"

            if section_title:
                # 参考文献章节标题 → 统一归一化为 __REFERENCES__，确保后续识别
                if ReferenceExtractor.is_reference_section(section_title):
                    block_key = "__REFERENCES__"
                else:
                    block_key = section_title
            elif is_heading_block:
                # 标题内容本身可能是参考文献标题 → 归一化
                heading_text = block.content[:60].strip()
                if ReferenceExtractor.is_reference_section(heading_text):
                    block_key = "__REFERENCES__"
                else:
                    block_key = heading_text
            elif is_reference_block:
                # 参考文献统一使用固定 section key，确保所有参考文献归入一组
                block_key = "__REFERENCES__"
            elif ChunkingService._looks_like_references(block.content):
                # 内容级兜底：layout_tag 缺失但文本特征强烈指向参考文献
                block_key = "__REFERENCES__"
                logger.debug(
                    f"内容级参考文献检测触发: page={block.page_number}, "
                    f"前80字={block.content[:80]}"
                )
            else:
                block_key = current_key  # 继承当前 section

            if block_key != current_key:
                if current_blocks:
                    groups.append((current_key, current_blocks))
                current_key = block_key
                current_blocks = [block]
            else:
                current_blocks.append(block)

        if current_blocks:
            groups.append((current_key, current_blocks))

        return groups

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
        """合并连续文本块；跨页时智能检测连字符、语义重叠、句末连续性。"""
        sorted_blocks = sorted(blocks, key=lambda b: (b.page_number, id(b)))
        if not sorted_blocks:
            return []
        merged: list[StructuredBlock] = [sorted_blocks[0]]
        for block in sorted_blocks[1:]:
            prev = merged[-1]
            prev_text = prev.content.rstrip()
            next_text = block.content.strip()

            # 同页合并：仅当 layout_tag 兼容时合并（避免正文吞掉参考文献等特殊块）
            if block.page_number == prev.page_number:
                # 不同 layout_tag 不合并，各自保留语义标签
                prev_tag = prev.layout_tag or ""
                cur_tag = block.layout_tag or ""
                if prev_tag and cur_tag and prev_tag != cur_tag:
                    merged.append(block)
                    continue
                merged[-1] = StructuredBlock(
                    block_type="text",
                    content=prev.content + "\n" + block.content,
                    page_number=prev.page_number,
                    bbox=prev.bbox,
                    section_title=prev.section_title or block.section_title,
                    section_path=prev.section_path or block.section_path,
                    layout_tag=prev.layout_tag or block.layout_tag,
                )
                continue

            # 跨页合并判断
            if block.page_number != prev.page_number + 1:
                merged.append(block)
                continue

            # 判断是否应该跨页合并
            should_merge, join_str = self._should_merge_cross_page(prev_text, next_text)
            if should_merge:
                # 不同 layout_tag 不跨页合并（避免跨页吞掉语义标签）
                prev_tag2 = prev.layout_tag or ""
                cur_tag2 = block.layout_tag or ""
                if prev_tag2 and cur_tag2 and prev_tag2 != cur_tag2:
                    merged.append(block)
                    continue
                merged[-1] = StructuredBlock(
                    block_type="text",
                    content=prev.content + join_str + block.content,
                    page_number=prev.page_number,
                    bbox=prev.bbox,
                    section_title=prev.section_title or block.section_title,
                    section_path=prev.section_path or block.section_path,
                    layout_tag=prev.layout_tag or block.layout_tag,
                )
            else:
                merged.append(block)
        return merged

    @staticmethod
    def _should_merge_cross_page(prev_text: str, next_text: str) -> tuple[bool, str]:
        """判断两个跨页文本块是否应合并，返回 (是否合并, 连接符)。

        检测逻辑（按优先级降级）：
        1. 断词连字符：prev 末尾 '-' + next 首字母小写 → 连字符拼接
        2. 后块为新章节/标题 → 不合并
        3. 前块句末完整 + 后块句首完整 → 不合并（两个独立段落）
        4. 语义重叠：prev 尾部 ~ next 头部 n-gram 重叠 → 去重合并
        5. 编号连续性：prev 末尾为 "3." + next 起始为 "4." → 合并
        6. 默认：合并（跨页连段落常见）
        """
        if not prev_text or not next_text:
            return False, "\n"

        prev_stripped = prev_text.rstrip()
        next_stripped = next_text.lstrip()

        # 1. 断词连字符检测（英文: informa-\ntion）
        if prev_stripped[-1] == "-" and next_stripped and next_stripped[0].islower():
            return True, ""

        # 2. 后块为标题/章节开头 → 不合并
        if ChunkingService._is_section_start(next_stripped):
            return False, "\n"

        # 3. 前块句末完整 → 默认不合并，除非有明确延续信号
        prev_ends_complete = prev_stripped[-1] in "。！？；.!?\"\"」』）)"
        if prev_ends_complete:
            return False, "\n"

        # 4. 编号/列表连续性检查
        if ChunkingService._is_sequential_numbering(prev_stripped, next_stripped):
            return True, "\n"  # 保持换行，保留编号结构

        # 5. 语义重叠检测：prev 尾部与 next 头部重叠 n-gram
        prev_tail = prev_stripped[-80:] if len(prev_stripped) > 80 else prev_stripped
        next_head = next_stripped[:80] if len(next_stripped) > 80 else next_stripped

        max_overlap = 0
        for overlap_len in range(min(40, len(prev_tail), len(next_head)), 2, -1):
            if prev_tail[-overlap_len:] == next_head[:overlap_len]:
                max_overlap = overlap_len
                break

        if max_overlap >= 3:
            return True, ""

        # 6. 默认：跨页合并
        return True, ""

    # ── 辅助检测函数 ─────────────────────────────────────────

    # 章节/标题开头模式
    _SECTION_START_RE = re.compile(
        r"^(?:"
        r"#{1,6}\s+"                         # Markdown 标题
        r"|第[一二三四五六七八九十百千\d]+[章节篇部条]"  # 中文数字章节
        r"|\d+(?:\.\d+)*\s+[A-Z一-鿿]"  # 编号标题 "1.1 概述"
        r"|[（(][一二三四五六七八九十\d]+[）)]"     # (一) (二)
        r"|(?:Abstract|Introduction|Method|Experiment|Results?|Conclusion|"
        r"Reference|Discussion|Acknowledgment|Appendix|Summary|Background|"
        r"Related\s+Work|Overview|Preliminaries?)\b"  # 英文标准章节
        r"|(?:摘要|绪论|引言|方法论|实验|结果|结论|讨论|致谢|附录|总结|"
        r"背景|相关工作|参考文献|参考书目)"             # 中文标准章节
        r"|[A-Z][A-Z\s]{2,40}\n"               # 全大写英文标题
        r")",
        re.IGNORECASE,
    )

    # 编号序列模式
    _NUMBERING_RE = re.compile(
        r"^(?:([\d]+|[a-zA-Z]|[ivxlcdm]+|[一二三四五六七八九十]+)[\.\、\)）])"
    )

    @classmethod
    def _is_section_start(cls, text: str) -> bool:
        """检测文本是否为新章节/段落的起始（不应合并到前一页）。"""
        stripped = text.strip()
        # 模式匹配
        if cls._SECTION_START_RE.match(stripped):
            return True
        # 极短行（<15字符）+ 后续换行 → 可能是独立标题
        first_line = stripped.split("\n")[0].strip()
        if len(first_line) < 15 and "\n" in stripped:  # noqa: SIM102
            # 检查是否像标题（首行短 + 以大写/CJK开头）
            if re.match(r"^[A-Z一-鿿]", first_line):
                return True
        return False

    @classmethod
    def _is_sequential_numbering(cls, prev: str, next_text: str) -> bool:
        """检测前后块是否属于同一个编号序列（如步骤 3 和步骤 4）。"""
        prev_last = prev.split("\n")[-1].strip()
        next_first = next_text.strip().split("\n")[0].strip()

        prev_m = cls._NUMBERING_RE.match(prev_last)
        next_m = cls._NUMBERING_RE.match(next_first)
        if not prev_m or not next_m:
            return False

        p_num = prev_m.group(1)
        n_num = next_m.group(1)

        # 尝试数值比较
        try:
            return cls._number_value(n_num) == cls._number_value(p_num) + 1
        except ValueError:
            return False

    _CN_NUMS = dict(zip("一二三四五六七八九十", range(1, 11), strict=False))
    _ROMAN_NUMS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5,
                   "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}

    @classmethod
    def _number_value(cls, s: str) -> int:
        """将编号字符串转为整数值。"""
        s_lower = s.lower()
        if s.isdigit():
            return int(s)
        if s_lower in cls._ROMAN_NUMS:
            return cls._ROMAN_NUMS[s_lower]
        if len(s_lower) == 1 and s_lower.isalpha():
            return ord(s_lower) - ord("a") + 1
        result = 0
        for ch in s:
            if ch in cls._CN_NUMS:
                result = result * 10 + cls._CN_NUMS[ch]
        return result if result > 0 else -1

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
        # 保留最具体的 layout_tag（优先级: reference > heading > 其他）
        best_tag = blocks[0].layout_tag
        for b in blocks[1:]:
            if b.layout_tag == "reference":
                best_tag = "reference"
                break
            if b.layout_tag in ("heading", "title", "subtitle") and best_tag not in ("reference",):
                best_tag = b.layout_tag
        return StructuredBlock(
            block_type="text",
            content=fused_content,
            page_number=blocks[0].page_number,
            bbox=blocks[0].bbox,
            section_title=blocks[0].section_title,
            section_path=blocks[0].section_path,
            layout_tag=best_tag,
        )

    _SPECIAL_CONTENT_MAX_CHARS = 1800  # 留空间给 _build_embed_text 添加的元数据头
    _HARD_CONTENT_MAX_CHARS = 6000  # 硬上限：任何 chunk 内容不得超过此值（embedding 模型安全边界）

    @classmethod
    def _hard_cap_content(cls, content: str) -> str:
        """强制截断过长内容，保证 embedding 模型安全。"""
        if len(content) <= cls._HARD_CONTENT_MAX_CHARS:
            return content
        truncated = content[:cls._HARD_CONTENT_MAX_CHARS]
        for sep in ("\n\n", "。", ". ", "\n", " ", ""):
            idx = truncated.rfind(sep)
            if idx > cls._HARD_CONTENT_MAX_CHARS // 2:
                return truncated[:idx + len(sep)] + f"\n...(已截断，原{len(content)}字符)"
        return truncated + f"...(已截断，原{len(content)}字符)"

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
            lang = self._detect_code_language(block.content)
            if lang:
                parts.append(f"[代码语言] {lang}")
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

        # 中文章节/正则类分隔符 —— 使用 re.split 而非 str.split
        is_regex_sep = separator in self._REGEX_SEPARATORS or separator.startswith("\n第")
        if is_regex_sep:
            # 根据实际分隔符生成对应的 re.split 模式
            if separator.startswith("\n第"):
                # 中文数字章节：第X章/节/篇/部
                if any(kw in separator for kw in ("条款",)):
                    pattern = r"(?=\n第[一二三四五六七八九十百千\d]+[条款])"
                else:
                    pattern = r"(?=\n第[一二三四五六七八九十百千]+[章节篇部])"
            elif r"\d+[\.\、]\d+[\.\、]" in separator:
                pattern = r"(?=\n\d+[\.\、]\d+)"
            elif any(kw in separator for kw in ("Abstract", "Introduction", "Method", "Experiment", "Result", "Conclusion", "Reference")):
                pattern = r"(?=\n(?:Abstract|Introduction|Method|Experiment|Results?|Conclusion|Reference|Discussion|Acknowledgments?))"
            else:
                pattern = separator
            splits = re.split(pattern, text)
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

        result_chunks: list[str] = []
        for chunk in chunks:
            if self._char_count(chunk) > chunk_size:
                result_chunks.extend(
                    self._recursive_split(
                        chunk, remaining_separators, chunk_size, chunk_overlap
                    )
                )
            else:
                result_chunks.append(chunk)
        return self._apply_overlap(result_chunks, chunk_overlap)

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
        """强制按有效字符数切割（带重叠），优先在标点处切断。

        重叠通过 step 移动自然产生（每个 chunk 的 start 只前进 chunk_size - chunk_overlap），
        因此不额外调用 _apply_overlap，避免双重重叠导致内容重复。
        """
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

        # 重叠已由 step_count 机制提供，不再调用 _apply_overlap
        return chunks

    def _apply_overlap(self, chunks: list[str], chunk_overlap: int) -> list[str]:
        """为相邻 chunk 添加重叠窗口，避免语义在边界处断裂。

        防御性去重：如果当前 chunk 的开头已包含重叠文本（如 _force_split
        已通过 step 移动提供了重叠），则跳过添加，避免双重重叠导致内容重复。
        """
        if chunk_overlap <= 0 or len(chunks) <= 1:
            return chunks
        result: list[str] = [chunks[0]]
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]  # 取原始前一块（未添加 overlap 的版本）
            overlap_text = self._tail_by_char_count(prev, chunk_overlap)
            current = chunks[i]
            # 防御性去重：current 开头已包含重叠内容则跳过
            if overlap_text and current.startswith(overlap_text):
                result.append(current)
            elif overlap_text:
                result.append(overlap_text + current)
            else:
                result.append(current)
        return result

    def _char_count(self, text: str) -> int:
        """计算文本的有效字符数（中文按 1，英文按 1/4）。"""
        chinese_chars = len(self._CHINESE_CHAR_PATTERN.findall(text))
        other_chars = len(text) - chinese_chars
        return chinese_chars + max(other_chars // 4, 1)

    # ---- Code language detection ----

    # 语言指纹：关键词集合 → 语言名
    _CODE_LANG_FINGERPRINTS: dict[frozenset[str], str] = {
        frozenset({"def ", "import ", "class ", "self", "__init__"}): "Python",
        frozenset({"function ", "const ", "let ", "=>", "console.log"}): "JavaScript",
        frozenset({"function ", "const ", "interface ", "type ", "export "}): "TypeScript",
        frozenset({"func ", "package ", "import (", "fmt."}): "Go",
        frozenset({"public class ", "System.out", "import java."}): "Java",
        frozenset({"#include", "int main", "printf", "std::"}): "C/C++",
        frozenset({"SELECT ", "FROM ", "WHERE ", "CREATE TABLE"}): "SQL",
        frozenset({"#!/bin/bash", "#!/bin/sh", "echo ", "if [[ "}): "Shell",
        frozenset({"#!/usr/bin/env python", "#!/usr/bin/python"}): "Python",
        frozenset({"using System;", "namespace ", "public class "}): "C#",
        frozenset({"require(", "module.exports", "npm "}): "JavaScript",
        frozenset({"<?php", "namespace ", "echo "}): "PHP",
        frozenset({"fn ", "let mut ", "impl ", "struct ", "cargo "}): "Rust",
        frozenset({"package ", "use strict", "sub ", "my "}): "Perl",
        frozenset({"<!DOCTYPE html", "<html", "<div ", "<script"}): "HTML",
        frozenset({"body {", "margin:", "padding:", "@media"}): "CSS",
        frozenset({"```yaml", "apiVersion:", "kind:", "metadata:"}): "YAML",
        frozenset({"```json", '"name":', '"version":', '"dependencies"'}): "JSON",
    }

    @classmethod
    def _detect_code_language(cls, text: str) -> str:
        """启发式推断代码块的语言。"""
        # 1. 围栏代码块的语言标记: ```python
        fence_match = re.match(r"^```(\S+)", text.strip())
        if fence_match:
            lang = fence_match.group(1).lower()
            if lang not in ("", "text", "plain", "sh"):
                return lang.capitalize()
            if lang == "sh":
                return "Shell"

        # 2. shebang 行
        shebang_match = re.match(r"^#!\s*\S*(\w+)\s*$", text.strip(), re.MULTILINE)
        if shebang_match:
            shebang = shebang_match.group(1).lower()
            shebang_map = {
                "python": "Python", "python3": "Python", "bash": "Shell",
                "sh": "Shell", "node": "JavaScript", "ruby": "Ruby",
                "perl": "Perl", "php": "PHP",
            }
            if shebang in shebang_map:
                return shebang_map[shebang]

        # 3. 关键词指纹匹配
        scores: dict[str, int] = {}
        text_lower = text.lower()
        for keywords, lang in cls._CODE_LANG_FINGERPRINTS.items():
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scores[lang] = scores.get(lang, 0) + score

        if scores:
            return max(scores, key=scores.get)  # type: ignore[arg-type]

        return ""

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
