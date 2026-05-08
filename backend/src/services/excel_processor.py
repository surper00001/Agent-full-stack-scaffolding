"""
Excel document processor - supports .xlsx / .xls parsing.
Features: multi-sheet, merged cells (rowspan/colspan), Markdown+HTML output, page tracking.
"""

from __future__ import annotations

from loguru import logger

from src.services.chunking_service import StructuredBlock


class ExcelProcessor:
    """Excel file processor - converts worksheet content to structured blocks."""

    def process(self, file_path: str) -> tuple[list[StructuredBlock], int, dict]:
        """Process Excel file, returns (blocks, page_count, metadata)."""
        try:
            import openpyxl
        except ImportError:
            raise ImportError("openpyxl not installed. Run: uv sync or pip install openpyxl")

        wb = openpyxl.load_workbook(file_path, data_only=True)
        blocks: list[StructuredBlock] = []
        metadata: dict = {
            "sheet_names": wb.sheetnames,
            "sheet_count": len(wb.sheetnames),
        }
        total_pages = 0

        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            if ws.max_row == 0 or ws.max_column == 0:
                continue

            merged_ranges = list(ws.merged_cells.ranges)
            merged_map = self._build_merged_map(merged_ranges)

            table_data = self._extract_table_data(ws, merged_map)
            if not table_data:
                continue

            page_count = max(1, (ws.max_row - 1) // 50 + 1)
            table_caption = sheet_name if sheet_name != "Sheet1" else None

            rows_per_page = 50
            for page_num in range(page_count):
                start_row = page_num * rows_per_page
                end_row = min((page_num + 1) * rows_per_page, len(table_data))
                page_data = table_data[start_row:end_row]

                if not page_data:
                    continue

                display_data = page_data
                if page_num > 0 and len(table_data) > 0:
                    display_data = [table_data[0]] + page_data

                md_table = self._table_to_markdown(display_data)
                html_table = self._table_to_html(display_data, merged_ranges)

                current_page = total_pages + page_num + 1
                blocks.append(StructuredBlock(
                    block_type="table",
                    content=md_table,
                    page_number=current_page,
                    table_html=html_table,
                    table_data=display_data,
                    table_caption=table_caption,
                    section_title=table_caption,
                ))

            total_pages += page_count

        logger.info(f"Excel done: sheets={len(wb.sheetnames)}, pages={total_pages}, blocks={len(blocks)}")
        wb.close()
        return blocks, max(total_pages, 1), metadata

    def _extract_table_data(self, ws, merged_map):
        """Extract worksheet data with merged cell handling."""
        data = []
        for row_idx, row in enumerate(ws.iter_rows(max_row=ws.max_row, max_col=ws.max_column), 1):
            row_data = []
            for col_idx, cell in enumerate(row, 1):
                key = (row_idx, col_idx)
                if key in merged_map:
                    mr_start_row, mr_start_col, _, _ = merged_map[key]
                    src_cell = ws.cell(row=mr_start_row, column=mr_start_col)
                    val = self._cell_to_str(src_cell.value)
                else:
                    val = self._cell_to_str(cell.value)
                row_data.append(val)
            if any(v.strip() for v in row_data):
                data.append(row_data)
        return data

    @staticmethod
    def _cell_to_str(value):
        if value is None:
            return ""
        if isinstance(value, float):
            if value == int(value):
                return str(int(value))
            return str(value)
        return str(value).strip()

    @staticmethod
    def _build_merged_map(merged_ranges):
        merged_map = {}
        for mr in merged_ranges:
            for row in range(mr.min_row, mr.max_row + 1):
                for col in range(mr.min_col, mr.max_col + 1):
                    merged_map[(row, col)] = (mr.min_row, mr.min_col, mr.max_row, mr.max_col)
        return merged_map

    @staticmethod
    def _table_to_markdown(table_data):
        if not table_data:
            return ""
        max_cols = max(len(row) for row in table_data)
        rows = []
        for i, row in enumerate(table_data):
            padded = list(row) + [""] * (max_cols - len(row))
            cleaned = [str(cell).replace("\n", " ").replace("|", r"\|").strip() for cell in padded]
            rows.append("| " + " | ".join(cleaned) + " |")
            if i == 0 and len(table_data) > 1:
                rows.append("| " + " | ".join(["---"] * max_cols) + " |")
        return "\n".join(rows)

    @staticmethod
    def _table_to_html(table_data, merged_ranges=None):
        if not table_data:
            return ""
        max_cols = max(len(row) for row in table_data)

        merge_attrs = {}
        if merged_ranges:
            for mr in merged_ranges:
                rowspan = mr.max_row - mr.min_row + 1
                colspan = mr.max_col - mr.min_col + 1
                attrs = {}
                if rowspan > 1:
                    attrs["rowspan"] = str(rowspan)
                if colspan > 1:
                    attrs["colspan"] = str(colspan)
                if attrs:
                    merge_attrs[(mr.min_row, mr.min_col)] = attrs

        parts = ['<div class="kb-table-wrapper"><table class="kb-table">']
        if table_data:
            parts.append("<thead><tr>")
            for j, cell in enumerate(table_data[0], 1):
                attrs = merge_attrs.get((1, j), {})
                attr_str = " " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) if attrs else ""
                parts.append(f"<th{attr_str}>{cell}</th>")
            parts.append("</tr></thead>")

            if len(table_data) > 1:
                parts.append("<tbody>")
                for i, row in enumerate(table_data[1:], 2):
                    parts.append("<tr>")
                    padded = list(row) + [""] * (max_cols - len(row))
                    for j, cell in enumerate(padded, 1):
                        attrs = merge_attrs.get((i, j), {})
                        attr_str = " " + " ".join(f'{k}="{v}"' for k, v in attrs.items()) if attrs else ""
                        parts.append(f"<td{attr_str}>{cell}</td>")
                    parts.append("</tr>")
                parts.append("</tbody>")

        parts.append("</table></div>")
        return "\n".join(parts)
