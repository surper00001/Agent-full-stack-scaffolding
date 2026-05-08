"""表格检测、验证、转换、合并工具。"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.services.chunking_service import StructuredBlock


class TableUtilsMixin:
    @classmethod
    def _blocks_to_full_text(cls, blocks: list[StructuredBlock]) -> str:
        """合并文本与表格内容供文档分析（中英文混合）。"""
        parts: list[str] = []
        for block in blocks:
            if block.block_type == "text":
                parts.append(block.content)
            elif block.block_type == "table" and block.table_data:
                md = cls._table_to_markdown(block.table_data)
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
        return any(cls._table_fingerprint(existing) == fp for existing in seen)


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


    _SENTENCE_PUNCTUATION = re.compile(r"[。！？.!?;；]")

    @classmethod
    def _is_valid_table(cls, table_data: list[list]) -> bool:
        """启发式过滤 pdfplumber/Camelot 误识别的「假表格」（结构 + 内容级）。"""
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
        all_cells: list[str] = []
        for row in rows:
            filled = [
                str(c).strip()
                for c in row
                if c is not None and str(c).strip()
            ]
            all_cells.extend(filled)
            row_len = len(row) if row else max_cols
            total_cells += max(row_len, max_cols)
            non_empty += len(filled)
            if len(filled) <= 1:
                single_cell_rows += 1

        if total_cells == 0 or non_empty / total_cells < 0.3:
            return False
        if single_cell_rows / len(rows) > 0.8:
            return False

        # 内容级：长句文本（含标点）>50% → 散文，非表格
        prose_cells = sum(
            1 for c in all_cells
            if len(c) > 40 and cls._SENTENCE_PUNCTUATION.search(c)
        )
        if prose_cells > len(all_cells) * 0.5:
            return False

        # 内容级：过高比例的超长单元格（>80 字符）→ 文字段落
        tall_cells = sum(1 for c in all_cells if len(c) > 80)
        if tall_cells > len(all_cells) * 0.6:
            return False

        # 内容级：编号列表（如 "1." "二、" "3）"）→ 非表格
        numbered_cells = sum(
            1 for c in all_cells
            if re.match(r"^[\d一二三四五六七八九十]+[\.、\)）]\s*\S", c) and len(c) < 80
        )
        if numbered_cells >= 3 and numbered_cells / len(all_cells) > 0.4:
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
        return not (dup_rows / len(rows) > 0.5)

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

