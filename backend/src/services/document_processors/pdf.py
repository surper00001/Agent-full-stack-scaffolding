"""PDF 文档解析——pdfplumber + PyMuPDF + Camelot + OCR。"""

from __future__ import annotations

import contextlib

from loguru import logger

from src.services.chunking_service import StructuredBlock


class PDFMixin:
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
                        section_title=self._detect_section_title(page_full_text.strip() or ""),
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

        # 按页码 + y 坐标排序，保持页面内从上到下的阅读顺序
        blocks.sort(key=lambda b: (b.page_number, b.bbox[1] if b.bbox else 999999))

        return blocks, page_count, metadata

    # ---- Word 处理 ----


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
            with contextlib.suppress(Exception):
                found_table_objs = page.find_tables() or []

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


    def _extract_page_text_regions(
        self,
        page: object,
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> list[tuple[str, tuple[float, float, float, float]]]:
        """提取非表格区域的文本块，每个区域返回独立 (text, bbox)。"""
        if not table_bboxes:
            text = page.extract_text() or ""
            if text.strip():
                return [(text.strip(), (0, 0, page.width, page.height))]
            return []

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

            results: list[tuple[str, tuple[float, float, float, float]]] = []
            for region in regions:
                w, h = region[2] - region[0], region[3] - region[1]
                if w < 20 or h < 8:
                    continue
                try:
                    cropped = page.within_bbox(region)
                    chunk = cropped.extract_text() if cropped else ""
                    if chunk and chunk.strip():
                        results.append((chunk.strip(), region))
                except Exception:
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


