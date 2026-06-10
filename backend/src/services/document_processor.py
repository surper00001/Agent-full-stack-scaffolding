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
from typing import TYPE_CHECKING, Any

# PaddlePaddle on Windows: 必须在任何 Paddle 导入之前禁用 OneDNN/MKL-DNN，
# 否则 PIR 图优化阶段会报 ConvertPirAttribute2RuntimeAttribute 错误
os.environ["FLAGS_use_onednn"] = "0"  # noqa: SIM112
os.environ["FLAGS_use_mkldnn"] = "0"  # noqa: SIM112

from loguru import logger

from src.core.config import get_settings
from src.services.chunking_service import StructuredBlock
from src.services.document_analyzer import (
    DocStructure,
    DocumentTypeAnalyzer,
    HeadingNode,
)
from src.services.document_processors.layout import DocxStyleTagger, LayoutTag
from src.services.document_processors.pdf import PDFMixin
from src.services.document_processors.table_utils import TableUtilsMixin
from src.services.vlm_service import get_vlm_service

if TYPE_CHECKING:
    from src.services.file_storage import FileStorageService


def _table_data_to_md(data: list[list[str]]) -> str:
    """二维列表 → Markdown 表格（用于 embedding text）。"""
    if not data:
        return ""
    rows = []
    for i, row in enumerate(data):
        cleaned = [str(c).replace("\n", " ").replace("|", "\\|").strip() for c in row]
        rows.append("| " + " | ".join(cleaned) + " |")
        if i == 0:
            rows.append("| " + " | ".join(["---"] * len(cleaned)) + " |")
    return "\n".join(rows)


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
        self._ocr: Any = None
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

        # 图文交叉引用锚点解析（「如图 3-2」→ 匹配实际图片块）
        from src.services.cross_reference_resolver import CrossReferenceResolver
        blocks = CrossReferenceResolver.resolve(blocks)

        # 列表嵌套结构分析（缩进层级 + 有序/无序区分）
        from src.services.document_processors.layout import enrich_list_structure
        blocks = enrich_list_structure(blocks)

        # 脚注/尾注链接（正文标记 → 脚注内容匹配）
        from src.services.footnote_resolver import FootnoteResolver
        blocks = FootnoteResolver.resolve(blocks)

        # 跨页模板噪声去重（重复水印、警告语、版权声明等）
        from src.services.document_processors.table_utils import TableUtilsMixin
        blocks = TableUtilsMixin._deduplicate_template_noise(blocks)

        # 深度元数据提取（DOI、摘要、关键词、作者等）
        from src.services.metadata_extractor import MetadataExtractor
        deep_meta = MetadataExtractor.extract(blocks, page_count, ext.lstrip("."))
        metadata["deep_metadata"] = deep_meta.to_dict()
        if deep_meta.title and not metadata.get("title"):
            metadata["title"] = deep_meta.title
        if deep_meta.authors and not metadata.get("author"):
            metadata["author"] = "; ".join(deep_meta.authors)
        if deep_meta.doi:
            metadata["doi"] = deep_meta.doi

        logger.info(
            f"文档分析完成: 类型={doc_structure.category.value} "
            f"(置信度={doc_structure.confidence:.0%}), "
            f"页数={page_count}, 块数={len(blocks)}, "
            f"章节={len(doc_structure.headings)}, "
            f"表格={doc_structure.table_count}, 图片={doc_structure.image_count}, "
            f"推荐分块={doc_structure.recommended_chunk_size}"
        )

        return blocks, page_count, metadata, doc_structure

    def _process_pdf(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        """处理 PDF 文件，优先使用 MinerU，失败则回退到 pdfplumber 管线。"""
        from src.services.document_processors.mineru import MinerUParser

        # 尝试 MinerU（如果配置启用）
        mineru = MinerUParser()
        if mineru.available:
            result = mineru.parse(file_path)
            if result is not None:
                blocks, page_count, metadata = result
                logger.info(
                    f"MinerU 解析成功: pages={page_count}, blocks={len(blocks)}"
                )
                # 将 MinerU 临时目录中的图片持久化到缩略图目录
                blocks = self._persist_mineru_images(blocks)
                # 仍然提取 PDF 内嵌图片并做 VLM OCR/描述（MinerU 可能漏图）
                blocks = self._enrich_with_pdf_images(file_path, blocks)
                return blocks, page_count, metadata

        # 回退到默认 pdfplumber + PyMuPDF 管线
        return PDFMixin._process_pdf_default(self, file_path)

    def _persist_mineru_images(
        self, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """将 MinerU 临时目录中的图片拷贝到缩略图目录，更新 image_path。

        MinerU 解析时 image_path 指向其临时输出目录（hash 文件名），
        这些文件可能被清理，需要持久化到 thumbnails 目录供前端访问。
        """
        if not self._save_ctx:
            return blocks

        from pathlib import Path

        idx = 0
        for block in blocks:
            if block.block_type != "image" or not block.image_path:
                continue
            idx += 1
            src = Path(block.image_path)
            if not src.exists():
                logger.warning(f"MinerU 图片源文件已不存在: {src}")
                continue
            try:
                img_bytes = src.read_bytes()
                ext = src.suffix.lstrip(".") or "png"
                page_num = block.page_number or 1
                new_path = self._storage.save_thumbnail(
                    self._save_ctx.tenant_id,
                    self._save_ctx.user_id,
                    self._save_ctx.kb_id,
                    self._save_ctx.doc_id,
                    page_num,
                    idx,
                    img_bytes,
                    ext,
                )
                object.__setattr__(block, "image_path", new_path)
            except Exception as e:
                logger.warning(f"MinerU 图片持久化失败: {e}")

        return blocks

    def _enrich_with_pdf_images(
        self, file_path: str, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """从 PDF 提取内嵌图片，追加为 image blocks（用于 MinerU 后补充 VLM OCR/描述）。"""
        import fitz

        doc = fitz.open(file_path)
        try:
            for page_num in range(doc.page_count):
                page = doc[page_num]
                image_list = page.get_images(full=True)
                for img_info in image_list:
                    xref = img_info[0]
                    try:
                        base_image = doc.extract_image(xref)
                        img_rects = page.get_image_rects(img_info)
                        bbox = None
                        if img_rects:
                            rect = img_rects[0]
                            bbox = (rect.x0, rect.y0, rect.x1, rect.y1)
                        caption = self._detect_image_caption(
                            blocks, page_num + 1, bbox
                        )
                        blocks.append(self._build_image_block(
                            page_num=page_num + 1,
                            img_bytes=base_image["image"],
                            ext=base_image.get("ext", "png"),
                            bbox=bbox,
                            caption=caption,
                        ))
                    except Exception as e:
                        logger.debug(f"PDF 图片提取失败 (page={page_num + 1}, xref={xref}): {e}")
        finally:
            doc.close()

        blocks.sort(key=lambda b: (b.page_number, b.bbox[1] if b.bbox else 999999))
        return blocks

    # ---- DOCX 处理 ----

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

        # 章节层级追踪
        heading_stack: list[tuple[int, str]] = []  # [(level, title), ...]

        def _build_section_path() -> str | None:
            if not heading_stack:
                return None
            return " > ".join(title for _, title in heading_stack)

        for element in doc.element.body:
            tag = element.tag.split("}")[-1] if "}" in element.tag else element.tag

            if tag == "p":
                if para_idx < len(doc.paragraphs):
                    para = doc.paragraphs[para_idx]
                    para_idx += 1

                    # 检测显式分页
                    for run in para.runs:
                        for br in run._element.findall(qn("w:br")):
                            if br.get(qn("w:type")) == "page":
                                current_page += 1
                                actual_page_count = max(actual_page_count, current_page)
                        if run._element.find(qn("w:lastRenderedPageBreak")) is not None:
                            current_page += 1
                            actual_page_count = max(actual_page_count, current_page)

                    # 提取段落内图片
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
                                            ext = rel.target_ref.rsplit(".", 1)[-1] if "." in (rel.target_ref or "") else "png"
                                            images_in_para.append({
                                                "bytes": rel.target_part.blob,
                                                "ext": ext,
                                            })
                                    except Exception as e:
                                        logger.debug(f"DOCX 图片提取失败: {e}")

                    text = para.text
                    if text.strip():
                        is_heading = para.style.name.startswith("Heading") if para.style else False
                        style_name = para.style.name if para.style else "Normal"
                        layout_tag = DocxStyleTagger.tag(style_name).value

                        if is_heading:
                            # 提取标题级别并维护层级栈
                            level_str = style_name.replace("Heading", "").strip()
                            try:
                                level = int(level_str)
                            except ValueError:
                                level = 1
                            current_section = text.strip()
                            # 弹出同级别及更低级别的标题
                            while heading_stack and heading_stack[-1][0] >= level:
                                heading_stack.pop()
                            heading_stack.append((level, current_section))

                            blocks.append(StructuredBlock(
                                block_type="text",
                                content=text.strip(),
                                page_number=current_page,
                                section_title=current_section,
                                section_path=_build_section_path(),
                                layout_tag=layout_tag,
                            ))
                        else:
                            blocks.append(StructuredBlock(
                                block_type="text",
                                content=text.strip(),
                                page_number=current_page,
                                section_title=current_section,
                                section_path=_build_section_path(),
                                layout_tag=layout_tag,
                            ))

                    for img_info in images_in_para:
                        img_block = self._build_image_block(
                            page_num=current_page,
                            img_bytes=img_info["bytes"],
                            ext=img_info.get("ext", "png"),
                            caption=text.strip() if text.strip() else None,
                            section_title=current_section,
                        )
                        img_block.layout_tag = LayoutTag.IMAGE_REGION.value
                        blocks.append(img_block)

            elif tag == "tbl":
                # 直接从 XML 元素提取表格（避免 python-docx 跳过合并单元格）
                table_rows = element.findall(qn("w:tr"))
                table_data: list[list[str]] = []
                colspans: list[list[int]] = []
                rowspans: list[list[int]] = []

                # vMerge 跨行状态追踪
                vmerge_tracker: dict[int, str] = {}  # col_idx -> "restart" | "continue"

                for row_el in table_rows:
                    cells = row_el.findall(qn("w:tc"))
                    row_data: list[str] = []
                    row_cs: list[int] = []
                    row_rs: list[int] = []

                    col_idx = 0
                    for cell_el in cells:
                        # gridSpan (colspan)
                        grid_span_el = cell_el.find(qn("w:tcPr") + "/" + qn("w:gridSpan")) if cell_el.find(qn("w:tcPr")) is not None else None
                        cs = int(grid_span_el.get(qn("w:val"), "1")) if grid_span_el is not None else 1

                        # vMerge (rowspan)
                        vmerge_el = cell_el.find(qn("w:tcPr") + "/" + qn("w:vMerge")) if cell_el.find(qn("w:tcPr")) is not None else None
                        rs = 1
                        if vmerge_el is not None:
                            vmerge_val = vmerge_el.get(qn("w:val"))
                            if vmerge_val == "restart":
                                vmerge_tracker[col_idx] = "restart"
                            elif vmerge_val is None or vmerge_val == "continue":
                                if col_idx in vmerge_tracker:
                                    rs = 0  # 被合并到上一行
                                vmerge_tracker[col_idx] = "continue"

                        # 提取纯文本
                        text_parts = []
                        for p_el in cell_el.findall(qn("w:p")):
                            t_els = p_el.findall(".//" + qn("w:t"))
                            line = "".join(t.text or "" for t in t_els)
                            if line:
                                text_parts.append(line)
                        cell_text = "\n".join(text_parts).strip()

                        row_data.append(cell_text)
                        row_cs.append(cs)
                        row_rs.append(rs)

                        col_idx += cs  # 按 gridSpan 推进列索引

                    table_data.append(row_data)
                    colspans.append(row_cs)
                    rowspans.append(row_rs)

                if table_data and len(table_data) >= 2:
                    md = self._table_to_markdown(table_data)
                    html = self._table_to_html(table_data, colspans=colspans, rowspans=rowspans)

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
                        table_data=table_data if table_data else None,
                        table_caption=table_caption,
                        section_title=current_section,
                        section_path=_build_section_path(),
                        layout_tag=LayoutTag.TABLE_BODY.value,
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

        # 提取原始尺寸
        img_width, img_height = None, None
        try:
            from io import BytesIO

            from PIL import Image
            with Image.open(BytesIO(img_bytes)) as pil_img:
                img_width, img_height = pil_img.size
        except Exception as e:
            logger.debug(f"图片尺寸检测失败: {e}")

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
        vlm_description: str | None = None
        vlm = get_vlm_service()

        # 第一层：PaddleOCR（快速、离线）
        if self._settings.kb_ocr_enabled:
            ocr_text, ocr_error = self._ocr_image(img_bytes)
            if ocr_text.strip():
                ocr_status = "success"
            elif ocr_error:
                ocr_status = "failed"
            else:
                ocr_status = "empty"

        # 第二层：VLM OCR 回退（对复杂版面/屏幕截图/艺术字更准）
        if (not ocr_text.strip()) and vlm.enabled:
            logger.info(f"PaddleOCR 未识别到文字 (status={ocr_status})，尝试 VLM OCR 回退")
            vlm_text, vlm_err = vlm.ocr_image(img_bytes, ext)
            if vlm_text.strip() and vlm_text.strip() != "无文字":
                ocr_text = vlm_text
                ocr_status = "vlm_success"
                ocr_error = None
                logger.info("VLM OCR 回退成功")
            elif vlm_err:
                if ocr_status in ("disabled", "empty"):
                    ocr_status = "failed"
                    ocr_error = f"PaddleOCR: {ocr_status}; VLM: {vlm_err}"

        # 第三层：VLM 图像描述（无论 OCR 是否成功，补充语义信息）
        if vlm.enabled:
            try:
                vlm_description, _ = vlm.describe_image(img_bytes, ext)
                if vlm_description.strip():
                    logger.info(f"VLM 图像描述生成成功: {vlm_description[:80]}...")
            except Exception as e:
                logger.debug(f"VLM 图像描述失败: {e}")

        # 第四层：VLM 表格检测（识别图片中的表格并提取结构化数据）
        table_html = None
        table_data = None
        is_table_image = False
        table_caption = caption  # 优先用检测到的 caption
        if vlm.enabled:
            try:
                table_result = vlm.detect_table_in_image(img_bytes, ext)
                if table_result:
                    table_html = table_result["table_html"]
                    table_data = table_result["table_data"]
                    is_table_image = True
                    table_caption = table_result.get("table_caption") or caption
                    logger.info(
                        f"VLM 检测到图片中的表格: rows={len(table_data)}"
                    )
            except Exception as e:
                logger.debug(f"VLM 表格检测失败: {e}")

        # 构建最终内容
        if is_table_image and table_html:
            # 图片中包含表格：以表格为主，图片描述为辅
            table_md = _table_data_to_md(table_data) if table_data else ""
            content = f"[表格(图片提取)] {table_caption or ''}\n{table_md}"
            if vlm_description and vlm_description.strip():
                content += f"\n[图片描述] {vlm_description.strip()}"
            block_type = "table"
        elif vlm_description and vlm_description.strip():
            content = f"[图片描述] {vlm_description.strip()}"
            if ocr_text.strip():
                content += f"\n[OCR] {ocr_text.strip()[:500]}"
            block_type = "image"
        elif ocr_text.strip():
            content = f"[图片文字] {ocr_text.strip()[:500]}"
            block_type = "image"
        else:
            content = "[图片] 未识别到文字"
            block_type = "image"

        return StructuredBlock(
            block_type=block_type,
            content=content,
            page_number=page_num,
            bbox=bbox,
            table_html=table_html,
            table_data=table_data,
            image_path=image_path,
            section_title=section_title,
            image_caption=caption if block_type == "image" else None,
            image_description=vlm_description if block_type == "image" else (
                vlm_description or None
            ),
            table_caption=table_caption if block_type == "table" else None,
            ocr_status=ocr_status,
            ocr_error=ocr_error,
            image_width=img_width,
            image_height=img_height,
        )

    def _ocr_image(self, image_bytes: bytes) -> tuple[str, str | None]:
        """OCR 识别，返回 (文本, 错误信息)。"""
        if self._ocr is None:
            try:
                # 限制 PaddlePaddle CPU 线程数，避免吃满全部核心
                try:
                    import paddle
                    paddle.set_device("cpu")  # type: ignore[attr-defined]
                except Exception as e:
                    logger.debug(f"Paddle 设备设置失败: {e}")
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
            r"^(?:参考文献|参考书目|引用文献|Bibliography|Works\s+Cited|Reference\s+List)\s*$",
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
            cropped = page.within_bbox(above_area)  # type: ignore[attr-defined]
            if cropped:
                text = cropped.extract_text()
                if text and len(text.strip()) < 300:
                    for line in reversed(text.strip().splitlines()):
                        line = line.strip()
                        if not line:
                            continue
                        if self._TABLE_CAPTION_RE.search(line) or len(line) < 120:
                            return str(line) if line else None
        except Exception as e:
            logger.debug(f"表格标题检测失败: {e}")
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

