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
        """检测纯文本中是否存在表格信号（表题 / 多列对齐行）。

        仅用于 Camelot 回退判断——pdfplumber 漏检但文本有表格标识的页面，
        再用 Camelot 尝试提取。多列对齐行需要更严格的证据：
        必须有 >=5 行且包含数字列（与纯文本列表区分）。
        """
        if not text or not text.strip():
            return False
        if cls._TABLE_CAPTION_RE.search(text):
            return True
        # 多列对齐回退：要求至少 5 行 + 至少一列以数字为主（与排版列表区分）
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        multi_col_lines: list[list[str]] = []
        for ln in lines:
            parts = re.split(r"\s{2,}|\t", ln)
            if len(parts) >= 3:
                multi_col_lines.append(parts)
        if len(multi_col_lines) < 5:
            return False
        # 检查是否存在数字列（至少 50% 的某列包含数字）
        max_cols = max(len(parts) for parts in multi_col_lines)
        has_numeric_col = False
        for ci in range(max_cols):
            nums = 0
            total = 0
            for parts in multi_col_lines:
                if ci < len(parts):
                    total += 1
                    if re.search(r"\d", parts[ci]):
                        nums += 1
            if total > 0 and nums / total >= 0.5:
                has_numeric_col = True
                break
        return has_numeric_col


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
    _SEPARATOR_ONLY = re.compile(r"^[\s\-—_=#*~·•…─-╿]{3,}$")
    _BULLET_LIST = re.compile(
        r"^[\d一二三四五六七八九十]+[\.、\)）]\s*\S|^[•·▪▸►➤✓✅❖■◆●○►]\s"
    )
    _NUMBERED_ITEM = re.compile(
        r"^[\d一二三四五六七八九十]+[\.、\)）]\s*\S"
    )

    @classmethod
    def _is_valid_table(cls, table_data: list[list]) -> bool:
        """启发式过滤 pdfplumber/Camelot 误识别的「假表格」。

        按顺序检查（任一步失败即拒绝）：
        1. 结构级 — 行数/列数/填充率
        2. 分隔线 — 全由横线/装饰符构成的假行
        3. 内容级 — 散文密度、超长段落、编号列表、列一致性
        """
        if not table_data or len(table_data) < 2:
            return False
        rows = [r for r in table_data if r is not None]
        if len(rows) < 2:
            return False

        # 归一化所有行到相同列数（用 None 补齐），便于列级分析
        max_cols = max((len(r) for r in rows), default=0)
        if max_cols < 2:
            return False
        norm_rows: list[list[str | None]] = []
        for r in rows:
            padded = list(r) + [None] * (max_cols - len(r))
            norm_rows.append(padded)

        # ---- 结构统计 ----
        non_empty = 0
        total_cells = len(rows) * max_cols
        single_cell_rows = 0
        all_cells: list[str] = []
        for row in rows:
            filled = [
                str(c).strip()
                for c in row
                if c is not None and str(c).strip()
            ]
            all_cells.extend(filled)
            if len(filled) <= 1:
                single_cell_rows += 1
        non_empty = len(all_cells)

        if total_cells == 0 or non_empty / total_cells < 0.3:
            return False
        if single_cell_rows / len(rows) > 0.8:
            return False

        # ---- 分隔线检测 ----
        # 如果某行全部单元格都是分隔符（如 "────"），则非表格
        sep_rows = 0
        for row in rows:
            cells = [
                str(c).strip() for c in row
                if c is not None and str(c).strip()
            ]
            if cells and all(
                cls._SEPARATOR_ONLY.match(c) for c in cells
            ):
                sep_rows += 1
        if sep_rows > 0 and sep_rows / len(rows) >= 0.25:
            # 超过 25% 的行为纯分隔线 → 非表格
            return False

        # ---- 内容级 ----
        # 1) 散文密度：含句末标点的长句占比 >40% → 自然段而非表格
        prose_cells = sum(
            1 for c in all_cells
            if len(c) >= 20 and cls._SENTENCE_PUNCTUATION.search(c)
        )
        if len(all_cells) > 0 and prose_cells / len(all_cells) > 0.4:
            return False

        # 2) 超长单元格：>80 字符的单元格占比 >50% → 段落
        tall_cells = sum(1 for c in all_cells if len(c) > 80)
        if len(all_cells) > 0 and tall_cells / len(all_cells) > 0.5:
            return False

        # 3) 编号 / 项目符号列表
        numbered_cells = sum(
            1 for c in all_cells
            if cls._NUMBERED_ITEM.match(c) and len(c) < 80
        )
        bullet_cells = sum(
            1 for c in all_cells
            if cls._BULLET_LIST.match(c) and len(c) < 80
        )
        list_cells = max(numbered_cells, bullet_cells)
        if list_cells >= 3 and len(all_cells) > 0 and list_cells / len(all_cells) > 0.4:
            return False

        # 4) 重复长文本行（同一行各列内容相同且 >30 字符）
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

        # ---- 列级一致性 ----
        # 真实表格：各列内容异构（有的列短标签，有的列长文本/数字）
        # 伪表格（对齐文本）：各列内容均质（每列都是相似的长文本）

        # 5) 列数稳定性：真实表格每行列数基本一致（最多差 1 列）
        col_counts = [len([c for c in r if c is not None]) for r in norm_rows]
        if max(col_counts) - min(col_counts) > 1:
            return False

        # 6) 列内容长度异构性：计算每列平均长度，若所有列都 >40 字符均值 → 对齐文本
        col_avg_lens: list[float] = []
        for ci in range(max_cols):
            col_cells = [
                str(norm_rows[ri][ci]).strip()
                for ri in range(len(norm_rows))
                if norm_rows[ri][ci] is not None and str(norm_rows[ri][ci]).strip()
            ]
            if col_cells:
                col_avg_lens.append(sum(len(c) for c in col_cells) / len(col_cells))
            else:
                col_avg_lens.append(0)

        # 如果所有非零列的平均长度都 >30，说明每列都是长文本 → 非表格
        non_zero_avgs = [a for a in col_avg_lens if a > 0]
        if non_zero_avgs and all(a > 30 for a in non_zero_avgs) and len(non_zero_avgs) >= 2:
            return False

        # 7) 列间内容相似度：真实表格每列内容类型差异大（名称 vs 数字 vs 描述）
        # 对齐文本：各列内容类型相似（都是自然语言句子）
        col_prose_ratios: list[float] = []
        for ci in range(max_cols):
            col_cells = [
                str(norm_rows[ri][ci]).strip()
                for ri in range(len(norm_rows))
                if norm_rows[ri][ci] is not None and str(norm_rows[ri][ci]).strip()
            ]
            if col_cells:
                prose = sum(
                    1 for c in col_cells
                    if len(c) >= 20 and cls._SENTENCE_PUNCTUATION.search(c)
                )
                col_prose_ratios.append(prose / len(col_cells))
            else:
                col_prose_ratios.append(0)

        # 若所有列（≥2列）的散文比都 >0.5 → 各列都是自然语言文本
        if len(col_prose_ratios) >= 2 and all(p > 0.5 for p in col_prose_ratios):
            return False

        return True

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

