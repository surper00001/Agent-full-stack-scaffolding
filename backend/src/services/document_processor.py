"""
文档处理器 —— Agentic RAG 核心。

支持 PDF (pdfplumber + PyMuPDF + Camelot)、Word (python-docx)、图片 (PaddleOCR)。
统一输出 StructuredBlock 列表，保留页码、位置、章节信息。

增强功能：
- 文档类型自动分析（学术论文/法律/技术/报告/通用）
- 图片上下文保留（标题、说明文字、周围文本）
- 表格语义增强（标题检测、上下文关联）
- 章节层级检测
- 代码块识别与保留
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from src.core.config import get_settings
from src.services.chunking_service import StructuredBlock
from src.services.document_analyzer import (
    DocStructure,
    DocumentTypeAnalyzer,
    HeadingNode,
)

if TYPE_CHECKING:
    from src.services.file_storage import FileStorageService


@dataclass
class _ImageSaveContext:
    tenant_id: str
    user_id: str
    kb_id: str
    doc_id: str


class DocumentProcessor:
    """统一文档解析器——自动识别文件类型并提取结构化内容。"""

    def __init__(self, file_storage: FileStorageService | None = None) -> None:
        from src.services.file_storage import FileStorageService as _FSS
        self._storage = file_storage or _FSS()
        self._settings = get_settings()
        self._ocr: object | None = None
        self._analyzer = DocumentTypeAnalyzer()
        self._save_ctx: _ImageSaveContext | None = None
        self._stored_path: str = ""
        self._img_counter = 0

    def process(
        self,
        stored_path: str,
        *,
        tenant_id: str | None = None,
        user_id: str | None = None,
        kb_id: str | None = None,
        doc_id: str | None = None,
    ) -> tuple[list[StructuredBlock], int, dict, DocStructure]:
        """处理存档文件，返回 (blocks, page_count, metadata, doc_structure)。"""
        self._stored_path = stored_path
        self._img_counter = 0
        if tenant_id and user_id and kb_id and doc_id:
            self._save_ctx = _ImageSaveContext(tenant_id, user_id, kb_id, doc_id)
        else:
            self._save_ctx = None
        file_path = self._storage.get_absolute_path(stored_path)
        ext = file_path.suffix.lower()

        logger.info(f"开始解析文档: {stored_path} (类型: {ext})")

        if ext == ".pdf":
            blocks, page_count, metadata = self._process_pdf(str(file_path))
        elif ext in (".docx", ".doc"):
            blocks, page_count, metadata = self._process_docx(str(file_path))
        elif ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif"):
            blocks, page_count, metadata = self._process_image(str(file_path), ext)
        elif ext in (".txt", ".md"):
            blocks, page_count, metadata = self._process_text(str(file_path))
        else:
            raise ValueError(f"不支持的文件类型: {ext}")

        blocks = self._merge_continued_tables(blocks)

        # 分析文档结构（文本 + 表格单元格均参与语言/类型判断）
        full_text = self._blocks_to_full_text(blocks)
        doc_structure = self._analyzer.analyze(full_text, blocks, page_count, ext)

        # 将章节信息回填到 block
        blocks = self._enrich_blocks_with_structure(blocks, doc_structure)

        logger.info(
            f"文档分析完成: 类型={doc_structure.category.value} "
            f"(置信度={doc_structure.confidence:.0%}), "
            f"页数={page_count}, 块数={len(blocks)}, "
            f"章节={len(doc_structure.headings)}, "
            f"表格={doc_structure.table_count}, 图片={doc_structure.image_count}, "
            f"推荐分块={doc_structure.recommended_chunk_size}"
        )

        return blocks, page_count, metadata, doc_structure

    # ---- PDF 处理 ----

    def _process_pdf(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        import fitz  # PyMuPDF
        import pdfplumber

        blocks: list[StructuredBlock] = []
        metadata: dict = {}

        # 1. PyMuPDF 提取元数据和图片
        doc = fitz.open(file_path)
        page_count = doc.page_count
        metadata["title"] = doc.metadata.get("title", "")
        metadata["author"] = doc.metadata.get("author", "")

        # 提取所有页面的图片 + 位置信息
        image_refs: dict[int, list[dict]] = {}
        for page_num in range(page_count):
            page = doc[page_num]
            image_list = page.get_images(full=True)
            page_images = []
            for img_info in image_list:
                xref = img_info[0]
                base_image = doc.extract_image(xref)
                # 获取图片在页面上的位置
                img_rects = page.get_image_rects(img_info)
                bbox = None
                if img_rects:
                    rect = img_rects[0]
                    bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                page_images.append({
                    "xref": xref,
                    "bytes": base_image["image"],
                    "ext": base_image["ext"],
                    "width": base_image["width"],
                    "height": base_image["height"],
                    "bbox": bbox,
                })
            image_refs[page_num + 1] = page_images
        doc.close()

        # 2. pdfplumber 提取文本和表格（先表格、后非表格区域文本）
        page_dimensions: dict[str, dict[str, float]] = {}
        page_text_hints: dict[int, str] = {}
        with pdfplumber.open(file_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_width = page.width
                page_height = page.height
                page_dimensions[str(page_num)] = {"width": page_width, "height": page_height}

                extracted = self._extract_page_tables_with_meta(page)
                table_bboxes = [item["bbox"] for item in extracted if item.get("bbox")]

                text = self._extract_page_text_outside_tables(page, table_bboxes)
                if text and text.strip():
                    section_title = self._detect_section_title(text)
                    blocks.append(StructuredBlock(
                        block_type="text",
                        content=text.strip(),
                        page_number=page_num,
                        bbox=(0, 0, page_width, page_height),
                        section_title=section_title,
                    ))
                    page_text_hints[page_num] = text

                for table_idx, item in enumerate(extracted):
                    table_data = item["data"]
                    table_bbox = item.get("bbox")
                    table_caption = item.get("caption") or self._detect_table_caption(
                        page, table_bbox
                    )
                    if not table_caption:
                        table_caption = self._caption_from_nearby_text(
                            page_text_hints.get(page_num, ""), table_idx
                        )
                    html_table = self._table_to_html(table_data)
                    md_table = self._table_to_markdown(table_data)
                    short_desc = f"[表格] {table_caption or f'第{page_num}页表格{table_idx + 1}'}"
                    blocks.append(StructuredBlock(
                        block_type="table",
                        content=f"{short_desc}\n\n{md_table}" if md_table else short_desc,
                        page_number=page_num,
                        bbox=table_bbox,
                        table_html=html_table,
                        table_data=table_data,
                        table_caption=table_caption,
                        section_title=self._detect_section_title(text or ""),
                    ))

                if not extracted:
                    logger.debug(f"第{page_num}页: pdfplumber 未检出有效表格")

        # 3. Camelot 补充：空白页 + 有表题/续表但无表格块的页
        pdfplumber_table_pages = {
            b.page_number for b in blocks if b.block_type == "table"
        }
        pages_with_text = {b.page_number for b in blocks if b.block_type == "text"}
        table_indicator_pages = {
            p for p, t in page_text_hints.items()
            if self._text_has_table_indicator(t) and p not in pdfplumber_table_pages
        }
        camelot_candidate_pages = sorted({
            p for p in range(1, page_count + 1)
            if p not in pdfplumber_table_pages
            and (p not in pages_with_text or p in table_indicator_pages)
        })
        if camelot_candidate_pages:
            existing_fps = {
                self._table_fingerprint(b.table_data)
                for b in blocks
                if b.block_type == "table" and b.table_data
            }
            blocks.extend(
                self._camelot_extract_tables(
                    file_path, camelot_candidate_pages, existing_fps
                )
            )

        # 3b. 扫描页整页 OCR 回退（无文本层或文本极少时）
        if self._settings.kb_page_ocr_fallback and self._settings.kb_ocr_enabled:
            pages_with_text = {b.page_number for b in blocks if b.block_type == "text"}
            ocr_pages = []
            for p in range(1, page_count + 1):
                if p in pages_with_text:
                    # 有文本但过短且本页无表格 → 可能是扫描页仅识别出页眉
                    text_len = len(page_text_hints.get(p, ""))
                    has_table = any(
                        b.block_type == "table" and b.page_number == p for b in blocks
                    )
                    if text_len >= 80 or has_table:
                        continue
                ocr_pages.append(p)
            if ocr_pages:
                blocks.extend(self._ocr_pdf_pages(file_path, ocr_pages, page_dimensions))

        # 4. 提取 PDF 内嵌图片（无论 OCR 成败都保存并回溯）
        for page_num, images in image_refs.items():
            for img_info in images:
                caption = self._detect_image_caption(
                    blocks, page_num, img_info.get("bbox")
                )
                blocks.append(self._build_image_block(
                    page_num=page_num,
                    img_bytes=img_info["bytes"],
                    ext=img_info.get("ext", "png"),
                    bbox=img_info.get("bbox"),
                    caption=caption,
                ))

        metadata["page_dimensions"] = page_dimensions
        return blocks, page_count, metadata

    # ---- Word 处理 ----

    def _process_docx(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(file_path)
        blocks: list[StructuredBlock] = []
        metadata: dict = {}

        if doc.core_properties:
            metadata["title"] = doc.core_properties.title or ""
            metadata["author"] = doc.core_properties.author or ""

        paragraph_count = len(doc.paragraphs)
        estimated_pages = max(1, paragraph_count // 30)

        current_page = 1
        para_idx = 0
        current_section: str | None = None

        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                if para_idx < len(doc.paragraphs):
                    para = doc.paragraphs[para_idx]
                    para_idx += 1

                    # 检测图片（DOCX 内嵌）
                    images_in_para = []
                    for run in para.runs:
                        for drawing in run._element.findall(qn("w:drawing")):
                            blips = drawing.findall(".//" + qn("a:blip"))
                            for blip in blips:
                                embed = blip.get(qn("r:embed"))
                                if embed:
                                    try:
                                        rel = para.part.rels[embed]
                                        if "image" in rel.reltype:
                                            # target_ref is like "media/image1.png" — extract extension
                                            ext = rel.target_ref.rsplit(".", 1)[-1] if "." in (rel.target_ref or "") else "png"
                                            images_in_para.append({
                                                "bytes": rel.target_part.blob,
                                                "ext": ext,
                                            })
                                    except Exception:
                                        pass

                    text = para.text
                    if text.strip():
                        is_heading = para.style.name.startswith("Heading") if para.style else False

                        if is_heading:
                            current_section = text.strip()
                            blocks.append(StructuredBlock(
                                block_type="text",
                                content=text.strip(),
                                page_number=current_page,
                                section_title=current_section,
                            ))
                        else:
                            blocks.append(StructuredBlock(
                                block_type="text",
                                content=text.strip(),
                                page_number=current_page,
                                section_title=current_section,
                            ))

                    # 处理内嵌图片（无论 OCR 成败都保存并回溯）
                    for img_info in images_in_para:
                        blocks.append(self._build_image_block(
                            page_num=current_page,
                            img_bytes=img_info["bytes"],
                            ext=img_info.get("ext", "png"),
                            caption=text.strip() if text.strip() else None,
                            section_title=current_section,
                        ))

                    if para_idx % 30 == 0:
                        current_page += 1

            elif tag == "tbl" and para_idx < len(doc.tables):
                table = doc.tables[para_idx % len(doc.tables)]
                table_data = []
                for row in table.rows:
                    row_data = [cell.text.strip() for cell in row.cells]
                    table_data.append(row_data)

                if table_data and len(table_data) >= 2:
                    md = self._table_to_markdown(table_data)
                    html = self._table_to_html(table_data)

                    # 检测表格标题（前一个段落）
                    table_caption = None
                    if para_idx > 1 and para_idx - 2 < len(doc.paragraphs):
                        prev_text = doc.paragraphs[para_idx - 2].text.strip()
                        if prev_text and len(prev_text) < 200:
                            table_caption = prev_text

                    blocks.append(StructuredBlock(
                        block_type="table",
                        content=md,
                        page_number=current_page,
                        table_html=html,
                        table_data=table_data,
                        table_caption=table_caption,
                        section_title=current_section,
                    ))

        return blocks, estimated_pages, metadata

    # ---- 图片处理 ----

    def _process_image(self, file_path: str, ext: str) -> tuple[list[StructuredBlock], int, dict]:
        img_bytes = Path(file_path).read_bytes()
        image_path = self._stored_path if self._save_ctx else None
        block = self._build_image_block(
            page_num=1,
            img_bytes=img_bytes,
            ext=ext.lstrip(".") or "png",
            image_path=image_path,
        )
        return [block], 1, {}

    # ---- 纯文本处理 ----

    def _process_text(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        text = Path(file_path).read_text(encoding="utf-8")
        lines = text.split("\n")

        # 检测代码块并保持完整
        blocks: list[StructuredBlock] = []
        in_code_block = False
        code_buffer: list[str] = []
        text_buffer: list[str] = []

        for line in lines:
            if line.strip().startswith("```") or line.strip().startswith("~~~"):
                if in_code_block:
                    # 代码块结束
                    code_buffer.append(line)
                    blocks.append(StructuredBlock(
                        block_type="code",
                        content="\n".join(code_buffer),
                        page_number=1,
                    ))
                    code_buffer = []
                    in_code_block = False
                else:
                    # 保存前面缓冲的文本
                    if text_buffer:
                        blocks.append(StructuredBlock(
                            block_type="text",
                            content="\n".join(text_buffer).strip(),
                            page_number=1,
                        ))
                        text_buffer = []
                    in_code_block = True
                    code_buffer.append(line)
            elif in_code_block:
                code_buffer.append(line)
            else:
                text_buffer.append(line)

        # 处理剩余
        if text_buffer:
            blocks.append(StructuredBlock(
                block_type="text",
                content="\n".join(text_buffer).strip(),
                page_number=1,
            ))
        if code_buffer:
            blocks.append(StructuredBlock(
                block_type="code",
                content="\n".join(code_buffer),
                page_number=1,
            ))

        pages = max(1, len(lines) // 50)
        return blocks, pages, {}

    # ---- OCR ----

    def _build_image_block(
        self,
        *,
        page_num: int,
        img_bytes: bytes,
        ext: str = "png",
        bbox: tuple[float, float, float, float] | None = None,
        caption: str | None = None,
        section_title: str | None = None,
        image_path: str | None = None,
    ) -> StructuredBlock:
        """构建图片块：先持久化图片，再尝试 OCR，成败都回溯给前端。"""
        self._img_counter += 1
        img_idx = self._img_counter

        if image_path is None and self._save_ctx:
            try:
                image_path = self._storage.save_thumbnail(
                    self._save_ctx.tenant_id,
                    self._save_ctx.user_id,
                    self._save_ctx.kb_id,
                    self._save_ctx.doc_id,
                    page_num,
                    img_idx,
                    img_bytes,
                    ext,
                )
            except Exception as e:
                logger.warning(f"图片存档失败 (page={page_num}, idx={img_idx}): {e}")

        ocr_status = "disabled"
        ocr_error: str | None = None
        ocr_text = ""

        if self._settings.kb_ocr_enabled:
            ocr_text, ocr_error = self._ocr_image(img_bytes)
            if ocr_error:
                ocr_status = "failed"
                content = "[图片] 未识别到文字，后续可接入多模态识别"
            elif ocr_text.strip():
                ocr_status = "success"
                content = f"[图片 OCR 结果] {ocr_text.strip()}"
            else:
                ocr_status = "empty"
                content = "[图片] 未识别到文字，后续可接入多模态识别"
        else:
            content = "[图片] 未识别到文字，后续可接入多模态识别"

        return StructuredBlock(
            block_type="image",
            content=content,
            page_number=page_num,
            bbox=bbox,
            image_path=image_path,
            section_title=section_title,
            image_caption=caption,
            image_description=ocr_text.strip() if ocr_text.strip() else None,
            ocr_status=ocr_status,
            ocr_error=ocr_error,
        )

    def _ocr_image(self, image_bytes: bytes) -> tuple[str, str | None]:
        """OCR 识别，返回 (文本, 错误信息)。"""
        if self._ocr is None:
            try:
                from paddleocr import PaddleOCR
                logger.info(f"初始化 PaddleOCR (lang={self._settings.kb_ocr_lang})")
                self._ocr = PaddleOCR(
                    lang=self._settings.kb_ocr_lang,
                    text_det_thresh=0.3,
                    text_det_box_thresh=0.4,
                )
            except Exception as e:
                logger.error(f"PaddleOCR 初始化失败: {e}")
                return "", str(e)

        try:
            import numpy as np
            from PIL import Image

            img = Image.open(io.BytesIO(image_bytes))
            img_array = np.array(img)

            result = self._ocr.ocr(img_array)
            if not result or not result[0]:
                return "", None

            lines = []
            for line_info in result[0]:
                text = line_info[1][0]
                confidence = line_info[1][1]
                if confidence > 0.5:
                    lines.append(text)

            return "\n".join(lines), None
        except Exception as e:
            logger.warning(f"OCR 识别失败: {e}")
            return "", str(e)

    # ---- 辅助方法 ----

    def _enrich_blocks_with_structure(
        self, blocks: list[StructuredBlock], structure: DocStructure
    ) -> list[StructuredBlock]:
        """将文档结构分析结果回填到 block 中。"""
        if not structure.headings:
            return blocks

        # 按页分配章节路径
        for block in blocks:
            if block.section_title:
                continue
            # 找最近的标题
            best_heading = self._find_nearest_heading(
                structure.headings, block.page_number
            )
            if best_heading:
                block.section_title = best_heading.title
                block.section_path = best_heading.to_path()

        return blocks

    def _find_nearest_heading(
        self, headings: list[HeadingNode], page: int
    ) -> HeadingNode | None:
        """在层级树中查找离指定页最近的标题。"""
        best: HeadingNode | None = None

        def walk(nodes: list[HeadingNode]) -> None:
            nonlocal best
            for node in nodes:
                if node.page is not None and node.page <= page:
                    best = node
                walk(node.children)

        walk(headings)
        return best

    def _detect_section_title(self, text: str) -> str | None:
        """从文本开头检测是否为章节标题。"""
        if not text:
            return None
        first_line = text.strip().split("\n")[0].strip()
        if len(first_line) > 200:
            return None

        patterns = [
            r"^#{1,6}\s+(.+)",
            r"^(第[一二三四五六七八九十百千\d]+[章节篇部条])\s*(.*)",
            r"^(\d+(?:\.\d+)*)\s+(.+)",
            r"^[（(][一二三四五六七八九十\d]+[）)]\s*(.+)",
            r"^(?:Chapter|Section|Part)\s+\d+[.:]?\s*(.+)",
            r"^(?:ABSTRACT|INTRODUCTION|REFERENCES)\b",
        ]
        for pattern in patterns:
            m = re.match(pattern, first_line)
            if m:
                return first_line
        return None

    def _detect_table_caption(self, page: object, table_bbox: tuple | None) -> str | None:
        """检测表格上方最近的短文本作为表格标题（中英文）。"""
        if table_bbox is None:
            return None
        try:
            above_area = (
                table_bbox[0],
                max(0, table_bbox[1] - 80),
                table_bbox[2],
                table_bbox[1],
            )
            cropped = page.within_bbox(above_area)
            if cropped:
                text = cropped.extract_text()
                if text and len(text.strip()) < 300:
                    for line in reversed(text.strip().splitlines()):
                        line = line.strip()
                        if not line:
                            continue
                        if self._TABLE_CAPTION_RE.search(line) or len(line) < 120:
                            return line
        except Exception:
            pass
        return None

    def _detect_image_caption(
        self, blocks: list[StructuredBlock], page_num: int, _img_bbox: tuple | None
    ) -> str | None:
        """检测图片周围文本作为图片标题/说明。"""
        # 简化实现：检查同页最近的文本块
        for block in reversed(blocks):
            if block.page_number == page_num and block.block_type == "text":
                # 取最后 100 字符（可能包含图片说明）
                tail = block.content[-200:]
                if len(tail.strip()) < 200 and (
                    "图" in tail or "Fig" in tail or "Figure" in tail
                ):
                    return tail.strip()
        return None

    # ---- 表格提取与校验 ----

    # 学术论文三线表：仅顶/表头/底线，无竖线 → vertical=text + horizontal=lines
    _TABLE_SETTINGS_LINES: dict = {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 5,
        "snap_tolerance": 3,
        "join_tolerance": 3,
    }
    _TABLE_SETTINGS_THREE_LINE: dict = {
        "vertical_strategy": "text",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 8,
        "snap_tolerance": 4,
        "join_tolerance": 4,
        "min_words_vertical": 1,
        "min_words_horizontal": 1,
    }
    _TABLE_SETTINGS_TEXT: dict = {
        "vertical_strategy": "text",
        "horizontal_strategy": "text",
        "snap_tolerance": 4,
        "join_tolerance": 4,
    }

    _TABLE_CAPTION_RE = re.compile(
        r"(?:^|\n)\s*(?:"
        r"表\s*\d+[^\n]{0,80}|"
        r"Tab\.?\s*\d+[^\n]{0,80}|"
        r"Table\s*\d+[^\n]{0,80}|"
        r"续表[^\n]{0,40}|"
        r"\(continued\)|"
        r"continued\s+from\s+table"
        r")",
        re.IGNORECASE | re.MULTILINE,
    )

    @staticmethod
    def _blocks_to_full_text(blocks: list[StructuredBlock]) -> str:
        """合并文本与表格内容供文档分析（中英文混合）。"""
        parts: list[str] = []
        for block in blocks:
            if block.block_type == "text":
                parts.append(block.content)
            elif block.block_type == "table" and block.table_data:
                md = DocumentProcessor._table_to_markdown(block.table_data)
                if md:
                    parts.append(md)
                if block.table_caption:
                    parts.append(block.table_caption)
        return "\n".join(parts)

    @classmethod
    def _text_has_table_indicator(cls, text: str) -> bool:
        if not text or not text.strip():
            return False
        if cls._TABLE_CAPTION_RE.search(text):
            return True
        # 多列对齐行（常见于未能框出表格时的 fallback 信号）
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        multi_col = sum(1 for ln in lines if len(re.split(r"\s{2,}|\t", ln)) >= 3)
        return multi_col >= 4

    @classmethod
    def _caption_from_nearby_text(cls, page_text: str, table_idx: int) -> str | None:
        if not page_text:
            return None
        matches = list(cls._TABLE_CAPTION_RE.finditer(page_text))
        if table_idx < len(matches):
            return matches[table_idx].group(0).strip()
        if matches:
            return matches[-1].group(0).strip()
        return None

    @staticmethod
    def _table_fingerprint(table_data: list[list]) -> tuple[int, int, tuple[str, ...]]:
        rows = [r for r in table_data if r is not None]
        max_cols = max((len(r) for r in rows), default=0)
        first = tuple(str(c or "").strip()[:24] for c in (rows[0] if rows else [])[:4])
        return len(rows), max_cols, first

    @classmethod
    def _is_duplicate_table(
        cls, table_data: list[list], seen: list[list[list]]
    ) -> bool:
        fp = cls._table_fingerprint(table_data)
        for existing in seen:
            if cls._table_fingerprint(existing) == fp:
                return True
        return False

    def _extract_page_tables_with_meta(self, page: object) -> list[dict]:
        """多策略提取表格，返回 data/bbox/caption 元信息。"""
        seen_data: list[list[list]] = []
        results: list[dict] = []

        strategies = [
            ("lines", self._TABLE_SETTINGS_LINES),
            ("three_line", self._TABLE_SETTINGS_THREE_LINE),
            ("text", self._TABLE_SETTINGS_TEXT),
            ("default", None),
        ]

        found_table_objs: list = []
        try:
            found_table_objs = page.find_tables(
                table_settings=self._TABLE_SETTINGS_THREE_LINE
            ) or []
        except Exception:
            try:
                found_table_objs = page.find_tables() or []
            except Exception:
                pass

        for _name, settings in strategies:
            try:
                raw = (
                    page.extract_tables()
                    if settings is None
                    else page.extract_tables(table_settings=settings)
                ) or []
            except Exception:
                continue
            for table_data in raw:
                if not self._is_valid_table(table_data):
                    continue
                if self._is_duplicate_table(table_data, seen_data):
                    continue
                seen_data.append(table_data)
                bbox = None
                if len(results) < len(found_table_objs):
                    try:
                        tb = found_table_objs[len(results)]
                        bbox = (tb.bbox[0], tb.bbox[1], tb.bbox[2], tb.bbox[3])
                    except Exception:
                        pass
                results.append({"data": table_data, "bbox": bbox, "caption": None})

        return results

    def _extract_page_tables(self, page: object) -> list[list[list[str | None]]]:
        """兼容旧接口。"""
        return [item["data"] for item in self._extract_page_tables_with_meta(page)]

    def _extract_page_text_outside_tables(
        self,
        page: object,
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> str:
        """提取非表格区域文本，避免表格单元格重复进入 text 块。"""
        if not table_bboxes:
            return page.extract_text() or ""

        try:
            page_area = (0, 0, page.width, page.height)
            regions: list[tuple[float, float, float, float]] = [page_area]
            for bbox in sorted(table_bboxes, key=lambda b: b[1]):
                x0, y0, x1, y1 = bbox
                pad = 2
                new_regions: list[tuple[float, float, float, float]] = []
                for rx0, ry0, rx1, ry1 in regions:
                    if y1 <= ry0 or y0 >= ry1:
                        new_regions.append((rx0, ry0, rx1, ry1))
                        continue
                    if ry0 < y0 - pad:
                        new_regions.append((rx0, ry0, rx1, min(ry1, y0 - pad)))
                    if ry1 > y1 + pad:
                        new_regions.append((rx0, max(ry0, y1 + pad), rx1, ry1))
                regions = new_regions

            parts: list[str] = []
            for region in regions:
                w, h = region[2] - region[0], region[3] - region[1]
                if w < 20 or h < 8:
                    continue
                try:
                    cropped = page.within_bbox(region)
                    chunk = cropped.extract_text() if cropped else ""
                    if chunk and chunk.strip():
                        parts.append(chunk.strip())
                except Exception:
                    continue
            if parts:
                return "\n\n".join(parts)
        except Exception as e:
            logger.debug(f"分区提取文本失败，回退整页: {e}")

        return page.extract_text() or ""

    def _camelot_extract_tables(
        self,
        file_path: str,
        page_nums: list[int],
        existing_fps: set[tuple[int, int, tuple[str, ...]]] | None = None,
    ) -> list[StructuredBlock]:
        """Camelot lattice + stream 双 flavor 补充表格。"""
        blocks: list[StructuredBlock] = []
        seen = set(existing_fps or ())
        try:
            import camelot
        except ImportError:
            logger.debug("Camelot 未安装")
            return blocks

        pages_spec = ",".join(str(p) for p in page_nums)
        added = 0
        for flavor in ("stream", "lattice"):
            try:
                camelot_tables = camelot.read_pdf(
                    file_path, pages=pages_spec, flavor=flavor
                )
            except Exception as e:
                logger.debug(f"Camelot {flavor} 失败: {e}")
                continue
            for ct in camelot_tables:
                data = ct.df.values.tolist()
                headers = [str(h) for h in ct.df.columns.tolist()]
                full_data = [headers] + data
                if not self._is_valid_table(full_data):
                    continue
                fp = self._table_fingerprint(full_data)
                if fp in seen:
                    continue
                seen.add(fp)
                page_no = int(ct.page)
                html = self._table_to_html(full_data)
                blocks.append(StructuredBlock(
                    block_type="table",
                    content=f"[表格] 第{page_no}页表格 (Camelot-{flavor})",
                    page_number=page_no,
                    table_html=html,
                    table_data=full_data,
                ))
                added += 1
        if added:
            logger.info(f"Camelot 补充 {added} 个表格（候选页 {len(page_nums)} 页）")
        return blocks

    @staticmethod
    def _is_continued_table_caption(caption: str | None) -> bool:
        if not caption:
            return False
        lower = caption.lower()
        markers = (
            "续表", "（续", "(续", "续）", "续)", "(continued)", "continued from", "cont'd",
        )
        return any(m in caption or m in lower for m in markers)

    @classmethod
    def _row_looks_like_header(cls, row: list) -> bool:
        if not row:
            return False
        filled = [str(c).strip() for c in row if c is not None and str(c).strip()]
        if len(filled) < 2:
            return False
        header_hints = (
            "类别", "category", "type", "组成", "component", "作用", "function",
            "role", "名称", "name", "描述", "description",
        )
        joined = " ".join(filled).lower()
        return any(h in joined for h in header_hints)

    def _merge_continued_tables(
        self, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """合并跨页续表（续表 / continued）到上一张表。"""
        if not blocks:
            return blocks

        sorted_blocks = sorted(
            blocks,
            key=lambda b: (b.page_number, 0 if b.block_type == "text" else 1),
        )
        merged: list[StructuredBlock] = []
        last_table: StructuredBlock | None = None

        for block in sorted_blocks:
            if block.block_type != "table":
                merged.append(block)
                continue

            caption = block.table_caption or block.content or ""
            is_continued = self._is_continued_table_caption(caption)

            if is_continued and last_table and last_table.table_data and block.table_data:
                extra_rows = list(block.table_data)
                if extra_rows and self._row_looks_like_header(extra_rows[0]):
                    extra_rows = extra_rows[1:]
                last_table.table_data = list(last_table.table_data) + extra_rows
                last_table.table_html = self._table_to_html(last_table.table_data)
                base_cap = last_table.table_caption or last_table.content
                last_table.content = f"{base_cap}（续，至第{block.page_number}页）"
                logger.info(
                    f"合并续表: 第{block.page_number}页 → 第{last_table.page_number}页起，"
                    f"+{len(extra_rows)} 行"
                )
                continue

            merged.append(block)
            last_table = block

        return merged

    @staticmethod
    def _is_valid_table(table_data: list[list]) -> bool:
        """启发式过滤 pdfplumber/Camelot 误识别的「假表格」。"""
        if not table_data or len(table_data) < 2:
            return False
        rows = [r for r in table_data if r is not None]
        if len(rows) < 2:
            return False
        max_cols = max((len(r) for r in rows), default=0)
        if max_cols < 2:
            return False

        non_empty = 0
        total_cells = 0
        single_cell_rows = 0
        for row in rows:
            filled = [
                str(c).strip()
                for c in row
                if c is not None and str(c).strip()
            ]
            row_len = len(row) if row else max_cols
            total_cells += max(row_len, max_cols)
            non_empty += len(filled)
            if len(filled) <= 1:
                single_cell_rows += 1

        if total_cells == 0 or non_empty / total_cells < 0.3:
            return False
        if single_cell_rows / len(rows) > 0.8:
            return False

        dup_rows = 0
        for row in rows:
            vals = [
                str(c).strip()
                for c in row
                if c is not None and str(c).strip()
            ]
            if len(vals) >= 2 and len(set(vals)) == 1 and len(vals[0]) > 30:
                dup_rows += 1
        if dup_rows / len(rows) > 0.5:
            return False
        return True

    def _ocr_pdf_pages(
        self,
        file_path: str,
        page_nums: list[int],
        page_dimensions: dict[str, dict[str, float]],
    ) -> list[StructuredBlock]:
        """对无文本层的 PDF 页整页渲染后 OCR。"""
        import fitz

        blocks: list[StructuredBlock] = []
        doc = fitz.open(file_path)
        try:
            for page_num in page_nums:
                if page_num < 1 or page_num > doc.page_count:
                    continue
                page = doc[page_num - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                img_bytes = pix.tobytes("png")
                ocr_text, ocr_err = self._ocr_image(img_bytes)
                if not ocr_text.strip():
                    if ocr_err:
                        logger.debug(f"第{page_num}页整页 OCR 失败: {ocr_err}")
                    continue
                dim = page_dimensions.get(str(page_num), {})
                pw = dim.get("width", float(page.rect.width))
                ph = dim.get("height", float(page.rect.height))
                blocks.append(StructuredBlock(
                    block_type="text",
                    content=ocr_text.strip(),
                    page_number=page_num,
                    bbox=(0, 0, pw, ph),
                    section_title=self._detect_section_title(ocr_text),
                ))
                logger.info(f"第{page_num}页整页 OCR 提取 {len(ocr_text)} 字符")
        finally:
            doc.close()
        return blocks

    # ---- 表格转换工具 ----

    @staticmethod
    def _table_to_markdown(table_data: list[list[str]]) -> str:
        if not table_data:
            return ""
        rows = []
        for i, row in enumerate(table_data):
            cleaned = [
                str(cell).replace("\n", " ").replace("|", "\\|").strip() if cell else ""
                for cell in row
            ]
            rows.append("| " + " | ".join(cleaned) + " |")
            if i == 0 and len(table_data) > 1:
                rows.append("| " + " | ".join(["---"] * len(cleaned)) + " |")
        return "\n".join(rows)

    @staticmethod
    def _table_to_html(table_data: list[list[str]]) -> str:
        if not table_data:
            return '<div class="kb-table-wrapper"><table class="kb-table"></table></div>'
        parts = ['<div class="kb-table-wrapper"><table class="kb-table">']
        for i, row in enumerate(table_data):
            tag = "th" if i == 0 else "td"
            cells = "".join(
                f"<{tag}>{str(cell).strip() if cell else ''}</{tag}>"
                for cell in row
            )
            parts.append(f"<tr>{cells}</tr>")
        parts.append("</table></div>")
        return "\n".join(parts)
