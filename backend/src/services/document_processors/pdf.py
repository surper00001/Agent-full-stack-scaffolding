"""PDF 文档解析——pdfplumber + PyMuPDF + Camelot + OCR + 版面分析。"""

from __future__ import annotations

import contextlib
import re
from typing import Any

from loguru import logger

from src.services.chunking.data_models import StructuredBlock
from src.services.document_processors.layout import (
    BlockTagger,
    FontInfo,
    LayoutTag,
    ReadingOrder,
    _extract_block_text,
    analyze_document_layout,
)
from src.services.document_processors.table_utils import TableUtilsMixin
from src.services.vlm_service import get_vlm_service


class PDFMixin(TableUtilsMixin):
    # 在解析过程中缓存 PyMuPDF text block dict，供 _extract_page_text_regions 使用
    _page_pymupdf_blocks: dict[int, list[dict]] = {}

    # ---- 以下方法/属性由 DocumentProcessor (document_processor.py) 在 MRO 中提供 ----

    _settings: Any
    _TABLE_SETTINGS_LINES: dict
    _TABLE_SETTINGS_THREE_LINE: dict
    _TABLE_SETTINGS_TEXT: dict

    def _detect_section_title(self, text: str) -> str | None:
        raise NotImplementedError

    def _detect_table_caption(self, page: Any, table_bbox: tuple | None) -> str | None:
        raise NotImplementedError

    def _detect_image_caption(self, blocks: list[StructuredBlock], page_num: int, _img_bbox: tuple | None) -> str | None:
        raise NotImplementedError

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
        raise NotImplementedError

    def _ocr_image(self, image_bytes: bytes) -> tuple[str, str | None]:
        raise NotImplementedError

    @staticmethod
    def _deep_scan_page_images(page: Any) -> list[tuple]:
        """递归扫描 XObject 树中可能被 get_images() 遗漏的图片。

        page.get_images(full=True) 在嵌套 Form XObject 较深时可能遗漏。
        此方法遍历页面的所有间接引用对象，找出未暴露给 get_images 的图片 xref。
        """
        results: list[tuple] = []
        doc = page.parent

        try:
            contents = page.get_contents()
            if not contents:
                return results
        except Exception as e:
            logger.debug(f"获取页面内容失败: {e}")
            return results

        seen: set[int] = set()
        stack: list[tuple[int, int]] = [(c, 0) for c in contents]

        while stack:
            xref, depth = stack.pop()
            if depth > 6 or xref in seen:
                continue
            seen.add(xref)

            try:
                obj_str = doc.xref_object(xref)
            except Exception as e:
                logger.debug(f"xref 对象解析失败 xref={xref}: {e}")
                continue

            if "/Subtype/Image" in obj_str.replace(" ", ""):
                results.append((xref, 0, 0, 0, 0, "", "", "", "", ""))
                continue

            if "/Subtype/Form" not in obj_str.replace(" ", ""):
                continue

            # 提取 Form XObject 中引用的子对象
            # 匹配间接引用：数字 数字 R（如 "12 0 R"）
            refs = re.findall(r"(\d+)\s+\d+\s+R", obj_str)
            for kid_xref_str in refs:
                with contextlib.suppress(ValueError):
                    stack.append((int(kid_xref_str), depth + 1))

        return results

    @staticmethod
    def _sort_by_reading_order(
        blocks: list[StructuredBlock],
        page_dimensions: dict[str, dict[str, float]],
    ) -> list[StructuredBlock]:
        """多栏布局感知的阅读顺序排序。

        对每页分别应用 ReadingOrder.reorder()，单栏页面退化为 y 坐标排序。
        """
        if len(blocks) <= 1:
            return blocks

        # 按页分组
        page_blocks: dict[int, list[StructuredBlock]] = {}
        for block in blocks:
            page_blocks.setdefault(block.page_number, []).append(block)

        reordered: list[StructuredBlock] = []
        for page_num in sorted(page_blocks.keys()):
            pb = page_blocks[page_num]
            if len(pb) <= 1:
                reordered.extend(pb)
                continue

            dim = page_dimensions.get(str(page_num), {"width": 595, "height": 842})
            pw = dim.get("width", 595)
            ph = dim.get("height", 842)

            # 转换为 ReadingOrder 期望的 dict 格式（保留原始对象引用）
            tagged: list[tuple[dict[str, object], StructuredBlock]] = []
            for block in pb:
                bbox = block.bbox or (0, 0, 0, 0)
                tagged.append(({"bbox": bbox, "text": block.content}, block))

            # 多栏阅读顺序恢复
            try:
                ordered_dicts = ReadingOrder.reorder(
                    [d for d, _ in tagged], pw, ph
                )
                # 映射回 StructuredBlock（通过 bbox+content 匹配）
                seen_ids: set[int] = set()
                for od in ordered_dicts:
                    ob = od.get("bbox", (0, 0, 0, 0))
                    ot = od.get("text", "")
                    for i, (d, block) in enumerate(tagged):
                        if i in seen_ids:
                            continue
                        if d["bbox"] == ob and d.get("text") == ot:
                            reordered.append(block)
                            seen_ids.add(i)
                            break
                    else:
                        # 精匹配失败，宽松匹配第一个未使用的
                        for i, (_, block) in enumerate(tagged):
                            if i not in seen_ids:
                                reordered.append(block)
                                seen_ids.add(i)
                                break
            except Exception as e:
                # 回退到 y 坐标排序
                logger.debug(f"精确排序失败，回退 y 坐标排序: {e}")
                reordered.extend(
                    sorted(pb, key=lambda b: b.bbox[1] if b.bbox else 999999)
                )

        return reordered

    def _process_pdf_default(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        import fitz  # PyMuPDF
        import pdfplumber

        blocks: list[StructuredBlock] = []
        metadata: dict = {}

        # 1. PyMuPDF 提取元数据、图片、字体信息（供版面分析）
        doc = fitz.open(file_path)
        page_count = doc.page_count
        metadata["title"] = doc.metadata.get("title", "")
        metadata["author"] = doc.metadata.get("author", "")

        image_refs: dict[int, list[dict]] = {}
        page_text_blocks: dict[int, list[dict]] = {}  # 供版面分析
        for page_num in range(page_count):
            page = doc[page_num]
            # 图片 —— 两步扫描：
            #   (1) page.get_images(full=True) 覆盖绝大多数情况
            #   (2) _deep_scan_page_images 递归遍历 XObject 补漏（嵌套 Form 中的图片）
            image_list = list(page.get_images(full=True))
            seen_xrefs = {img[0] for img in image_list}
            deep_images = self._deep_scan_page_images(page)
            for di in deep_images:
                if di[0] not in seen_xrefs:
                    image_list.append(di)
                    seen_xrefs.add(di[0])
            if deep_images:
                logger.debug(
                    f"第{page_num + 1}页: get_images={len(image_list) - len(deep_images)}, "
                    f"深层XObject补漏={len(deep_images)}"
                )

            page_images = []
            for img_info in image_list:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                except Exception:
                    logger.warning(f"第{page_num + 1}页 xref={xref} 图片提取失败，跳过")
                    continue
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
            # 字体文本块（版面分析用 + 细粒度文本拆分用）
            try:
                tb = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE).get("blocks", [])
                page_text_blocks[page_num + 1] = tb
            except Exception as e:
                logger.debug(f"第{page_num+1}页文本块提取失败: {e}")
                page_text_blocks[page_num + 1] = []
        doc.close()

        # 缓存 PyMuPDF blocks 供 _extract_page_text_regions 细粒度拆分
        self._page_pymupdf_blocks = page_text_blocks

        # 1b. 全文档版面分析
        layout = analyze_document_layout(page_count, page_text_blocks, {})
        logger.info(
            f"版面分析完成: body={layout.global_body_size:.1f}pt, "
            f"title={layout.global_title_size:.1f}pt, "
            f"页眉模式={len(layout.header_patterns)}, 页脚模式={len(layout.footer_patterns)}"
        )

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

                text_regions = self._extract_page_text_regions(page, table_bboxes)
                page_full_text = ""
                for region_text, region_bbox in text_regions:
                    section_title = self._detect_section_title(region_text)
                    blocks.append(StructuredBlock(
                        block_type="text",
                        content=region_text,
                        page_number=page_num,
                        bbox=region_bbox,
                        section_title=section_title,
                    ))
                    page_full_text += region_text + "\n"
                if page_full_text:
                    page_text_hints[page_num] = page_full_text.strip()

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

                    # 合并单元格检测：优先使用 pdfplumber Table 几何信息
                    colspans, rowspans = None, None
                    pdfplumber_table = item.get("pdfplumber_table")
                    if pdfplumber_table is not None:
                        cell_bboxes, col_x, row_y = self._pdfplumber_table_cell_info(
                            pdfplumber_table
                        )
                        colspans, rowspans = self._detect_merged_cells(
                            table_data,
                            cell_bboxes=cell_bboxes if cell_bboxes else None,
                            col_x_boundaries=col_x if col_x else None,
                            row_y_boundaries=row_y if row_y else None,
                        )
                    else:
                        colspans, rowspans = self._detect_merged_cells(table_data)

                    has_merges = any(
                        any(v != 1 for v in row)
                        for row in (colspans or [])
                    ) or any(
                        any(v != 1 for v in row)
                        for row in (rowspans or [])
                    )

                    # 多级表头检测
                    header_rows, _header_tree = self._detect_multi_level_headers(
                        table_data, colspans
                    )

                    if header_rows > 1:
                        html_table = self._build_table_html_with_headers(
                            table_data, colspans, rowspans, header_rows
                        )
                    else:
                        html_table = self._table_to_html(table_data, colspans, rowspans)

                    md_table = self._table_to_markdown(table_data, colspans, rowspans)
                    short_desc = f"[表格] {table_caption or f'第{page_num}页表格{table_idx + 1}'}"
                    blocks.append(StructuredBlock(
                        block_type="table",
                        content=f"{short_desc}\n\n{md_table}" if md_table else short_desc,
                        page_number=page_num,
                        bbox=table_bbox,
                        table_html=html_table,
                        table_data=table_data,
                        table_caption=table_caption,
                        section_title=self._detect_section_title(page_full_text.strip() or ""),
                    ))
                    if has_merges:
                        logger.debug(
                            f"第{page_num}页表格{table_idx + 1}: 检测到合并单元格"
                        )
                    if header_rows > 1:
                        logger.debug(
                            f"第{page_num}页表格{table_idx + 1}: 多级表头 ({header_rows} 级)"
                        )

                if not extracted:
                    logger.debug(f"第{page_num}页: pdfplumber 未检出有效表格")

        # 2b. 公式检测：识别行间/行内公式（字体 + 数学符号密度启发式）
        formula_count = 0
        for block in blocks:
            if block.block_type == "text" and _is_formula_block(block.content):
                block.block_type = "formula"
                block.layout_tag = LayoutTag.FORMULA.value
                formula_count += 1
        if formula_count:
            logger.info(f"公式检测: {formula_count} 个公式块已标记")

        # 2c. 版面语义标签分配（综合字体+位置+内容模式）
        tagged_count = 0
        for block in blocks:
            page_dim = page_dimensions.get(str(block.page_number), {"width": 595, "height": 842})
            pw = page_dim.get("width", 595)
            ph = page_dim.get("height", 842)
            font = _best_font_for_block(block, page_text_blocks.get(block.page_number, []))
            if block.block_type == "text":
                block.layout_tag = BlockTagger.tag_text_block(
                    block.content, font, pw, ph, block.bbox,
                    body_font_size=layout.global_body_size,
                    page_num=block.page_number,
                    total_pages=page_count,
                ).value
            elif block.block_type == "table":
                block.layout_tag = LayoutTag.TABLE_BODY.value
            elif block.block_type == "image":
                block.layout_tag = LayoutTag.IMAGE_REGION.value
            if block.layout_tag:
                tagged_count += 1
        logger.info(f"版面标签分配完成: {tagged_count}/{len(blocks)} 个块已标记")

        # 3. Camelot 补充：空白页 + 有表题/续表但无表格块的页
        pdfplumber_table_pages = {
            b.page_number for b in blocks if b.block_type == "table"
        }
        existing_fps = {
            self._table_fingerprint(b.table_data)
            for b in blocks
            if b.block_type == "table" and b.table_data
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
            blocks.extend(
                self._camelot_extract_tables(
                    file_path, camelot_candidate_pages, existing_fps
                )
            )

        # 3c. VLM 智能回退：对 pdfplumber + Camelot 均未检出表格但文本有表格信号的页，
        # 渲染页面图片后由 Qwen3-VL-Flash 视觉识别表格结构
        if self._settings.kb_vlm_table_extraction:
            current_table_pages = {b.page_number for b in blocks if b.block_type == "table"}
            vlm_candidate_pages = [
                p for p in range(1, page_count + 1)
                if p not in current_table_pages
                and self._text_has_table_indicator(page_text_hints.get(p, ""))
            ]
            if vlm_candidate_pages:
                blocks.extend(
                    self._vlm_extract_page_tables(
                        file_path, vlm_candidate_pages, existing_fps
                    )
                )
                # Merge continued tables again (VLM may have found continued table fragments)
                blocks = self._merge_continued_tables(blocks)

        # 3d. 多层防护：字符级回退 → OCR → 末尾页增强 OCR
        late_page_start = max(1, int(page_count * 0.8))  # 末尾 20%
        pages_with_text = {b.page_number for b in blocks if b.block_type == "text"}
        empty_or_short_pages = set()

        # ── Layer C: pdfplumber chars 级回退 ──
        # 当 PyMuPDF 返回空 blocks 时，用 pdfplumber 字符级提取重建文本行
        # chars API 比 text API 对小字号（7-8pt）更友好
        if self._settings.kb_page_ocr_fallback and self._settings.kb_ocr_enabled:
            with pdfplumber.open(file_path) as _pdf:
                for p in range(1, page_count + 1):
                    text_len = len(page_text_hints.get(p, ""))
                    if text_len >= 80:
                        continue
                    has_table = any(
                        b.block_type == "table" and b.page_number == p for b in blocks
                    )
                    if has_table and text_len >= 30:
                        continue
                    empty_or_short_pages.add(p)

            if empty_or_short_pages:
                # 先用 chars 级提取兜底
                chars_blocks = self._extract_chars_level(file_path, sorted(empty_or_short_pages), page_dimensions)
                if chars_blocks:
                    existing_pages = {b.page_number for b in blocks}
                    for cb in chars_blocks:
                        if cb.page_number in existing_pages and cb.content:
                            # 合并到现有块中（追加，不覆盖）
                            for existing in blocks:
                                if existing.page_number == cb.page_number and existing.block_type == "text":
                                    if cb.content not in existing.content:
                                        existing.content = existing.content + "\n" + cb.content
                                    break
                            else:
                                blocks.append(cb)
                        elif cb.content:
                            blocks.append(cb)
                    logger.info(f"Chars 级回退提取: {len(chars_blocks)} 个文本块")

                # ── Layer A+B: 末尾页增强 OCR（3x 分辨率）──
                late_empty = [p for p in empty_or_short_pages if p >= late_page_start]
                other_empty = [p for p in empty_or_short_pages if p < late_page_start]
                # 其他页用标准 2x OCR
                if other_empty:
                    blocks.extend(self._ocr_pdf_pages(file_path, other_empty, page_dimensions, matrix_scale=2))
                # 末尾页用 3x OCR（小字号参考文献需要更高分辨率）
                if late_empty:
                    blocks.extend(self._ocr_pdf_pages(file_path, late_empty, page_dimensions, matrix_scale=3))
                    logger.info(f"末尾 {len(late_empty)} 页使用 3x 增强 OCR（小字号参考文献）")

        # ── Layer D: 末尾页参考文献重分类 ──
        # 末尾 20% 页面的 BODY 块，如果包含 DOI/URL/年份/编号特征 → 强制改为 REFERENCE
        _reclassify_late_page_blocks(blocks, page_count)

        # ── VLM 直提: 末尾 3 页强制用 VLM 专用 prompt 提取参考文献 ──
        # 不再依赖"是否已有 reference 标记"作为触发条件，
        # VLM 专用 prompt 直接输出结构化参考文献条目，跳过文本→分类→分块的脆弱链路
        vlm_ref_blocks = _vlm_extract_references(file_path, page_count, page_dimensions)
        if vlm_ref_blocks:
            # VLM 专用 prompt 提取的参考文献是末尾页的权威结果，
            # 移除末尾 3 页的所有 text 块（包括已标记为 reference 的，避免重复）
            last_page_nums = set(range(max(1, page_count - 2), page_count + 1))
            ", ".join(str(p) for p in sorted(last_page_nums))
            removed_count = 0
            kept_blocks = []
            for b in blocks:
                if b.page_number in last_page_nums and b.block_type == "text":
                    removed_count += 1
                    continue  # VLM 结果替代
                kept_blocks.append(b)
            blocks = kept_blocks
            blocks.extend(vlm_ref_blocks)
            logger.info(
                f"VLM 提取参考文献: {len(vlm_ref_blocks)} 个块, "
                f"覆盖末尾 {len(last_page_nums)} 页 (移除 {removed_count} 个旧 text 块)"
            )

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

        # 按页码 + 阅读顺序排序：多栏布局感知（单栏退化为 y 坐标排序）
        blocks = self._sort_by_reading_order(blocks, page_dimensions)

        return blocks, page_count, metadata

    # ---- Word 处理 ----


    def _extract_page_tables_with_meta(self, page: Any) -> list[dict]:
        """多策略提取表格，返回 data/bbox/caption/pdfplumber_table 元信息。"""
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
        except Exception as e:
            logger.debug(f"三线表检测失败，回退通用检测: {e}")
            with contextlib.suppress(Exception):
                found_table_objs = page.find_tables() or []

        for _name, settings in strategies:
            try:
                raw = (
                    page.extract_tables()
                    if settings is None
                    else page.extract_tables(table_settings=settings)
                ) or []
            except Exception as e:
                logger.debug(f"表格提取失败 [{_name}]: {e}")
                continue
            for table_data in raw:
                if not self._is_valid_table(table_data):
                    continue
                if self._is_duplicate_table(table_data, seen_data):
                    continue
                seen_data.append(table_data)
                bbox = None
                pdfplumber_table = None
                if len(results) < len(found_table_objs):
                    try:
                        tb = found_table_objs[len(results)]
                        bbox = (tb.bbox[0], tb.bbox[1], tb.bbox[2], tb.bbox[3])
                        pdfplumber_table = tb
                    except Exception as e:
                        logger.debug(f"表格 bbox 提取失败: {e}")
                results.append({
                    "data": table_data,
                    "bbox": bbox,
                    "caption": None,
                    "pdfplumber_table": pdfplumber_table,
                })

        return results

    def _extract_page_tables(self, page: Any) -> list[list[list[str | None]]]:

        """兼容旧接口。"""
        return [item["data"] for item in self._extract_page_tables_with_meta(page)]


    def _extract_page_text_regions(
        self,
        page: Any,
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> list[tuple[str, tuple[float, float, float, float]]]:
        """提取非表格区域的文本块，每个区域返回独立 (text, bbox)。

        当页面无表格时，使用 PyMuPDF 的 text-block 级别拆分，
        确保参考文献等独立段落能被 _block_tagger 单独识别。
        """
        if not table_bboxes:
            # 优先用 PyMuPDF 文本块进行细粒度拆分
            py_blocks = self._page_pymupdf_blocks.get(page.page_number, [])
            if py_blocks:
                regions: list[tuple[str, tuple[float, float, float, float]]] = []
                for pb in py_blocks:
                    if pb.get("type") != 0:  # type 0 = text
                        continue
                    text = _extract_block_text(pb).strip()
                    if text:
                        bbox = tuple(pb.get("bbox", (0, 0, 0, 0)))
                        regions.append((text, bbox))
                if regions:
                    return regions
            # 回退：整页提取
            text = page.extract_text() or ""
            if text.strip():
                return [(text.strip(), (0, 0, page.width, page.height))]
            return []

        try:
            page_area = (0, 0, page.width, page.height)
            bbox_regions: list[tuple[float, float, float, float]] = [page_area]
            for bbox in sorted(table_bboxes, key=lambda b: b[1]):
                x0, y0, x1, y1 = bbox
                pad = 2
                new_regions: list[tuple[float, float, float, float]] = []
                for rx0, ry0, rx1, ry1 in bbox_regions:
                    if y1 <= ry0 or y0 >= ry1:
                        new_regions.append((rx0, ry0, rx1, ry1))
                        continue
                    if ry0 < y0 - pad:
                        new_regions.append((rx0, ry0, rx1, min(ry1, y0 - pad)))
                    if ry1 > y1 + pad:
                        new_regions.append((rx0, max(ry0, y1 + pad), rx1, ry1))
                bbox_regions = new_regions

            results: list[tuple[str, tuple[float, float, float, float]]] = []
            for region in bbox_regions:
                w, h = region[2] - region[0], region[3] - region[1]
                if w < 20 or h < 8:
                    continue
                try:
                    cropped = page.within_bbox(region)
                    chunk = cropped.extract_text() if cropped else ""
                    if chunk and chunk.strip():
                        results.append((chunk.strip(), region))
                except Exception as e:
                    logger.debug(f"OCR 区域文本提取失败 region={region}: {e}")
                    continue
            return results
        except Exception as e:
            logger.debug(f"分区提取文本失败，回退整页: {e}")

        text = page.extract_text() or ""
        if text.strip():
            return [(text.strip(), (0, 0, page.width, page.height))]
        return []


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
            from camelot import read_pdf as _camelot_read_pdf  # type: ignore[attr-defined]
        except ImportError:
            logger.debug("Camelot 未安装")
            return blocks

        pages_spec = ",".join(str(p) for p in page_nums)
        added = 0
        for flavor in ("stream", "lattice"):
            try:
                camelot_tables = _camelot_read_pdf(
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
                colspans, rowspans = self._detect_merged_cells(full_data)
                header_rows, _ = self._detect_multi_level_headers(full_data, colspans)
                if header_rows > 1:
                    html = self._build_table_html_with_headers(
                        full_data, colspans, rowspans, header_rows
                    )
                else:
                    html = self._table_to_html(full_data, colspans, rowspans)
                md = self._table_to_markdown(full_data)
                blocks.append(StructuredBlock(
                    block_type="table",
                    content=f"[表格] 第{page_no}页表格 (Camelot-{flavor})\n\n{md}" if md else f"[表格] 第{page_no}页表格 (Camelot-{flavor})",
                    page_number=page_no,
                    table_html=html,
                    table_data=full_data,
                ))
                added += 1
        if added:
            logger.info(f"Camelot 补充 {added} 个表格（候选页 {len(page_nums)} 页）")
        return blocks



    def _vlm_extract_page_tables(
        self,
        file_path: str,
        page_nums: list[int],
        existing_fps: set[tuple[int, int, tuple[str, ...]]] | None = None,
    ) -> list[StructuredBlock]:
        """用 VLM（Qwen3-VL-Flash）从 PDF 页面中提取表格。

        将页面渲染为图片，发送给 VLM 识别表格结构，
        绕过 pdfplumber/Camelot 的几何限制。
        """
        vlm = get_vlm_service()
        if not vlm.enabled:
            return []

        import fitz

        blocks: list[StructuredBlock] = []
        seen = set(existing_fps or ())
        max_pages = self._settings.kb_vlm_table_extraction_max_pages
        candidate = page_nums[:max_pages]

        if len(page_nums) > max_pages:
            logger.info(
                f"VLM 表格提取候选页 {len(page_nums)} 页，"
                f"限制处理前 {max_pages} 页"
            )

        doc = fitz.open(file_path)
        try:
            for page_num in candidate:
                try:
                    page = doc[page_num - 1]
                    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                    img_bytes = pix.tobytes("png")

                    tables, err = vlm.extract_tables(img_bytes, "png")
                    if err:
                        logger.warning(f"第{page_num}页 VLM 表格提取失败: {err}")
                        continue

                    for table_data in tables:
                        if not self._is_valid_table(table_data):
                            continue
                        fp = self._table_fingerprint(table_data)
                        if fp in seen:
                            continue
                        seen.add(fp)
                        colspans, rowspans = self._detect_merged_cells(table_data)
                        header_rows, _ = self._detect_multi_level_headers(table_data, colspans)
                        if header_rows > 1:
                            html = self._build_table_html_with_headers(
                                table_data, colspans, rowspans, header_rows
                            )
                        else:
                            html = self._table_to_html(table_data, colspans, rowspans)
                        md = self._table_to_markdown(table_data)
                        short_desc = f"[表格] 第{page_num}页表格 (VLM)"
                        blocks.append(StructuredBlock(
                            block_type="table",
                            content=f"{short_desc}\n\n{md}" if md else short_desc,
                            page_number=page_num,
                            table_html=html,
                            table_data=table_data,
                        ))
                        logger.info(f"第{page_num}页 VLM 提取表格 {len(table_data)} 行 x {len(table_data[0]) if table_data else 0} 列")
                except Exception as e:
                    logger.warning(f"第{page_num}页 VLM 处理异常: {e}")
                    continue
        finally:
            doc.close()

        if blocks:
            logger.info(f"VLM 共补充 {len(blocks)} 个表格")
        return blocks

    def _extract_chars_level(
        self,
        file_path: str,
        page_nums: list[int],
        page_dimensions: dict[str, dict[str, float]],
        char_gap: float = 6.0,
        line_gap: float = 4.0,
    ) -> list[StructuredBlock]:
        """pdfplumber chars 级提取 + 坐标聚类重建文本行（Layer C）。

        pdfplumber 的 chars API 对小字号（7-8pt）文本比 extract_text() 更友好，
        因为它是直接读取 PDF 内容流中每个字符的位置和字号，不依赖渲染引擎。
        """
        blocks: list[StructuredBlock] = []
        try:
            import pdfplumber

            with pdfplumber.open(file_path) as pdf:
                for page_num in page_nums:
                    if page_num < 1 or page_num > len(pdf.pages):
                        continue
                    page = pdf.pages[page_num - 1]
                    chars = page.chars
                    if not chars:
                        continue

                    # 按 y 坐标聚类成行（容差 line_gap）
                    chars_sorted = sorted(chars, key=lambda c: (round(c["top"], 1), c["x0"]))
                    lines: list[list[dict]] = []
                    for ch in chars_sorted:
                        if lines and abs(ch["top"] - lines[-1][0]["top"]) <= line_gap:
                            lines[-1].append(ch)
                        else:
                            lines.append([ch])

                    # 每行按 x0 排序，拼接文本
                    line_texts: list[tuple[str, float, float, float, float]] = []
                    for line in lines:
                        line.sort(key=lambda c: c["x0"])
                        text = ""
                        last_x1 = None
                        for ch in line:
                            if last_x1 is not None and ch["x0"] - last_x1 > char_gap:
                                text += " "
                            text += ch.get("text", "")
                            last_x1 = ch["x1"]
                        if text.strip():
                            y0 = min(c["top"] for c in line)
                            y1 = max(c["bottom"] for c in line)
                            x0 = min(c["x0"] for c in line)
                            x1 = max(c["x1"] for c in line)
                            line_texts.append((text.strip(), x0, y0, x1, y1))

                    if not line_texts:
                        continue

                    # 合并相邻行为段落块
                    para_blocks: list[list[tuple[str, float, float, float, float]]] = []
                    for lt in line_texts:
                        if para_blocks and abs(lt[2] - para_blocks[-1][-1][3]) <= line_gap * 3:
                            para_blocks[-1].append(lt)
                        else:
                            para_blocks.append([lt])

                    for para in para_blocks:
                        content = "\n".join(t[0] for t in para)
                        x0 = min(t[1] for t in para)
                        y0 = min(t[2] for t in para)
                        x1 = max(t[3] for t in para)
                        y1 = max(t[4] for t in para)
                        dim = page_dimensions.get(str(page_num), {})
                        dim.get("width", x1 + 10)
                        dim.get("height", y1 + 10)
                        blocks.append(StructuredBlock(
                            block_type="text",
                            content=content,
                            page_number=page_num,
                            bbox=(x0, y0, x1, y1),
                            section_title=self._detect_section_title(content),
                        ))

            if blocks:
                logger.info(f"Chars 级回退成功: {len(page_nums)} 页 → {len(blocks)} 个文本块")
        except Exception as e:
            logger.debug(f"Chars 级提取失败: {e}")
        return blocks

    def _ocr_pdf_pages(
        self,
        file_path: str,
        page_nums: list[int],
        page_dimensions: dict[str, dict[str, float]],
        matrix_scale: int = 2,
    ) -> list[StructuredBlock]:
        """对无文本层的 PDF 页整页渲染后 OCR。

        Args:
            matrix_scale: 渲染倍率，2=标准，3=增强（小字号文本需要更高分辨率）
        """
        import fitz

        blocks: list[StructuredBlock] = []
        doc = fitz.open(file_path)
        try:
            for page_num in page_nums:
                if page_num < 1 or page_num > doc.page_count:
                    continue
                page = doc[page_num - 1]
                pix = page.get_pixmap(matrix=fitz.Matrix(matrix_scale, matrix_scale))
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

    # (see table_utils.py for _table_to_markdown, _table_to_html, etc.)


# ── Layer D: 末尾页参考文献重分类 ───────────────────────────


def _reclassify_late_page_blocks(blocks: list[StructuredBlock], page_count: int) -> None:
    """末尾 20% 页面的 BODY 块若含参考文献特征 → 强制标为 REFERENCE。

    参考文献页的整页文本块经 OCR 后，classify_block 常无法识别为 REFERENCE
    （因为整页开头是"参考文献"标题而非条目编号）。此函数作为兜底重扫。
    """
    late_page_start = max(1, int(page_count * 0.8))

    # DOI/URL/卷期号/年份/编号 模式
    ref_content_patterns = [
        r"DOI[：:\s]|doi\.org/|10\.\d{4,}/",
        r"Vol\.\s*\d+|pp\.\s*\d+|No\.\s*\d+",
        r"\[?\d{4}\]?[;，,\s]",
        r"J\.[\s\d]|Journal\s+of",
        r"硕士学位论文|博士学位论文|arXiv|PMID",
        r"^\[\d+\]\s",
        r"\b(19|20)\d{2}[;，,]\s",
    ]
    import re as _re
    # 注意：必须加 MULTILINE 标志，否则 ^\[\d+\] 不会匹配行中间的引用编号
    _ref_re = _re.compile("|".join(ref_content_patterns), _re.IGNORECASE | _re.MULTILINE)

    reclassified = 0
    for block in blocks:
        if block.page_number < late_page_start:
            continue
        if block.block_type != "text":
            continue
        # 扩大重分类范围：除了 None/body，也处理被误标为 heading/subtitle 的块
        # 末尾页的 heading/subtitle 很可能是"参考文献"标题行被 BlockTagger 误判
        if block.layout_tag in ("header", "footer", "template_noise"):
            continue
        content = block.content or ""
        if len(content) < 50:
            continue

        matches = len(_ref_re.findall(content))
        # 末尾页文本块包含 ≥2 个文献特征 → 高置信度为参考文献
        # （从 3 降到 2，因为参考文献条目如 "[1] IEEE Standard 802.11, 2020" 只有 2 个特征）
        if matches >= 2:
            from src.services.document_processors.layout import LayoutTag
            block.layout_tag = LayoutTag.REFERENCE.value
            reclassified += 1

    if reclassified:
        logger.info(f"末尾页重新分类: {reclassified} 个块标记为 REFERENCE")


# ── VLM 兜底: 参考文献提取 ──────────────────────────────────


# ── VLM 专用参考文献提取 ───────────────────────────────────

# 专用 prompt：要求 VLM 逐条输出结构化参考文献
_VLM_REF_PROMPT = """你是一个学术文档分析助手。请仔细阅读这张文档页面图片，
提取其中所有的参考文献条目。

要求：
1. 逐条列出，每条以 "[数字]" 开头，如 [1]、[2]...
2. 每条包含：作者、标题、期刊/会议/出版社、年份、卷期页码
3. 如果有 DOI，请保留
4. 如果某条跨页不完整（如只有后半段），也请尽量列出
5. 忽略页眉页脚和无关文字
6. 用中文或原文输出即可，不要加额外解释

如果没有参考文献，请回复 "无参考文献"。

格式示例：
[1] 张三, 李四. 数字孪生系统架构研究[J]. 计算机学报, 2023, 46(3): 500-520.
[2] Smith J, Doe R. Forest management optimization[C]. Proc of IEEE, 2022: 100-110.
"""


def _vlm_extract_references(
    file_path: str,
    page_count: int,
    page_dimensions: dict[str, dict[str, float]],
) -> list[StructuredBlock]:
    """VLM 专用参考文摘提取：末尾 3 页逐页渲染后让 VLM 用专用 prompt 提取。

    与通用 OCR 不同，这里直接要求 VLM 输出带编号的结构化参考文献，
    跳过文本分类和 ReferenceExtractor 的脆弱解析环节。
    """
    from src.services.vlm_service import VLMService

    vlm = VLMService()
    if not vlm.enabled:
        logger.warning(
            "VLM 参考文献提取跳过: VLM 服务未启用。"
            "请配置 DASHSCOPE_API_KEY 环境变量以启用视觉模型兜底提取。"
        )
        return []

    import fitz
    blocks: list = []
    last_pages = list(range(max(1, page_count - 2), page_count + 1))

    doc = fitz.open(file_path)
    try:
        for page_num in last_pages:
            if page_num < 1 or page_num > doc.page_count:
                continue
            page = doc[page_num - 1]
            # 3x 高分辨率渲染，保证小字号参考文献清晰
            pix = page.get_pixmap(matrix=fitz.Matrix(3, 3))
            img_bytes = pix.tobytes("png")

            try:
                text, err = vlm.chat_with_image(_VLM_REF_PROMPT, img_bytes, "png")
                if err:
                    logger.debug(f"VLM 参考文摘失败 p{page_num}: {err}")
                    # 回退到通用 OCR
                    text, _ = vlm.ocr_image(img_bytes, "png")
            except Exception as e:
                logger.debug(f"VLM 参考文摘异常 p{page_num}: {e}")
                text, _ = vlm.ocr_image(img_bytes, "png")

            if not text or len(text.strip()) < 15:
                continue
            if "无参考文献" in text:
                continue

            # VLM 输出应包含逐条编号的参考文献
            dim = page_dimensions.get(str(page_num), {})
            pw = dim.get("width", float(page.rect.width))
            ph = dim.get("height", float(page.rect.height))
            from src.services.document_processors.layout import LayoutTag
            blocks.append(StructuredBlock(
                block_type="text",
                content=text.strip(),
                page_number=page_num,
                bbox=(0, 0, pw, ph),
                layout_tag=LayoutTag.REFERENCE.value,
            ))
            logger.info(f"VLM 参考文摘 p{page_num}: {len(text)} 字符")
    finally:
        doc.close()

    return blocks


# ── Layout helper ──────────────────────────────────────────────


def _best_font_for_block(
    block: StructuredBlock,
    page_blocks: list[dict],
) -> FontInfo | None:
    """从 PyMuPDF 文本块中找出与给定 block 位置最匹配的字体信息。"""
    from src.services.document_processors.layout import FontInfo

    if not page_blocks or not block.bbox:
        return None

    bx0, by0, bx1, by1 = block.bbox
    best_overlap = 0.0
    best_font: FontInfo | None = None

    for pb in page_blocks:
        if pb.get("type") != 0:  # type 0 = text
            continue
        pb_bbox = pb.get("bbox", (0, 0, 0, 0))
        px0, py0, px1, py1 = pb_bbox

        # 计算重叠面积
        ox0 = max(bx0, px0)
        oy0 = max(by0, py0)
        ox1 = min(bx1, px1)
        oy1 = min(by1, py1)
        overlap = max(0, ox1 - ox0) * max(0, oy1 - oy0)

        if overlap <= best_overlap:
            continue

        # 提取字体信息（取第一个 span）
        for line in pb.get("lines", []):
            for span in line.get("spans", []):
                best_font = FontInfo(
                    size=float(span.get("size", 10)),
                    bold=bool(span.get("flags", 0) & 8),
                    italic=bool(span.get("flags", 0) & 2),
                    font_name=span.get("font", ""),
                )
                best_overlap = overlap
                break
            break

    return best_font


# ── 公式检测启发式 ──────────────────────────────────────────
# 已提取到 src/services/document_processors/formula_utils.py
# 保留兼容别名，避免破坏现有 import 路径

from src.services.document_processors.formula_utils import (  # noqa: E402
    is_formula_block as _is_formula_block,  # noqa: F401
)
