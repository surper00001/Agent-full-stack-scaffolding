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
import os
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
from src.services.document_processors.pdf import PDFMixin
from src.services.document_processors.table_utils import TableUtilsMixin

if TYPE_CHECKING:
    from src.services.file_storage import FileStorageService


@dataclass
class _ImageSaveContext:
    tenant_id: str
    user_id: str
    kb_id: str
    doc_id: str


class DocumentProcessor(PDFMixin, TableUtilsMixin):
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

    def _process_docx(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        from docx import Document
        from docx.oxml.ns import qn

        doc = Document(file_path)
        blocks: list[StructuredBlock] = []
        metadata: dict = {}

        if doc.core_properties:
            metadata["title"] = doc.core_properties.title or ""
            metadata["author"] = doc.core_properties.author or ""

        current_page = 1
        actual_page_count = 1
        para_idx = 0
        current_section: str | None = None

        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                if para_idx < len(doc.paragraphs):
                    para = doc.paragraphs[para_idx]
                    para_idx += 1

                    # 检测显式分页符（<w:br w:type="page"/> 或 <w:lastRenderedPageBreak/>）
                    for run in para.runs:
                        for br in run._element.findall(qn("w:br")):
                            if br.get(qn("w:type")) == "page":
                                current_page += 1
                                actual_page_count = max(actual_page_count, current_page)
                        if run._element.find(qn("w:lastRenderedPageBreak")) is not None:
                            current_page += 1
                            actual_page_count = max(actual_page_count, current_page)

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

        return blocks, actual_page_count, metadata

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
                os.environ.setdefault("FLAGS_use_onednn", "0")
                from paddleocr import PaddleOCR
                logger.info(f"初始化 PaddleOCR (lang={self._settings.kb_ocr_lang})")
                self._ocr = PaddleOCR(
                    lang=self._settings.kb_ocr_lang,
                    use_angle_cls=False,
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

