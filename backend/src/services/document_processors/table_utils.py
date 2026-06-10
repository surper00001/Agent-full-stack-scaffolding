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
        return not (len(col_prose_ratios) >= 2 and all(p > 0.5 for p in col_prose_ratios))

    # ── 重复内容去重（模板噪声） ──────────────────────────────

    @classmethod
    def _deduplicate_template_noise(
        cls, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """检测并标记跨页重复出现的模板噪声。委托给独立模块。"""
        from src.services.document_processors.template_noise_filter import (
            deduplicate_template_noise,
        )
        return deduplicate_template_noise(blocks)

    # ── 多级表头识别 ────────────────────────────────────────

    @classmethod
    def _detect_multi_level_headers(
        cls,
        table_data: list[list[str]],
        colspans: list[list[int]] | None = None,
    ) -> tuple[int, dict[int, list[int]]]:
        """检测多级表头层级，返回 (header_row_count, header_tree)。

        多级表头示例：
          |    2024年度    |    2025年度    |  ← row 0 (level-0 parent headers)
          |  Q1  |  Q2  |  Q3  |  Q4  |   ← row 1 (level-1 child headers)
          | 100  | 200  | 150  | 180  |   ← data rows

        检测规则：
        1. 连续的表头行（每行所有列都是短标签 < 30 字符）
        2. 上层行非空单元格数 < 下层行 → 存在层级关系
        3. 利用 colspan 确定父子映射

        Returns:
            header_row_count: 表头行数（0 = 无表头，1 = 单级，2+ = 多级）
            header_tree: {parent_col_idx: [child_col_indices]} 或空 dict
        """
        if not table_data or len(table_data) < 3:
            return min(1, len(table_data)), {}

        rows = len(table_data)

        # 检测连续表头行：使用区分性更强的启发式
        _has_text = re.compile(r"[A-Za-z一-鿿]")
        _is_numeric = re.compile(r"^[\d.,+\-±%￥$€£\s]+$")
        header_rows = 0
        for ri in range(min(5, rows)):
            row = table_data[ri]
            cells = [str(c).strip() for c in row if c and str(c).strip()]
            if not cells:
                break

            # 排除条件1：含句末标点 → 不是表头
            has_sentence_end = any(re.search(r"[。！？.!?]", c) for c in cells)
            if has_sentence_end:
                break

            # 排除条件2：高比例纯数字 → 数据行
            numeric_ratio = sum(1 for c in cells if _is_numeric.match(c)) / len(cells)
            if numeric_ratio > 0.3:
                break

            # 排除条件3：超长单元格 → 数据行
            if any(len(c) > 60 for c in cells):
                break

            # 表头确认：至少 40% 单元格含文字字符
            text_ratio = sum(1 for c in cells if _has_text.search(c)) / len(cells)
            if text_ratio >= 0.4:
                header_rows += 1
            else:
                break

        if header_rows < 2:
            return max(1, header_rows), {}

        # 构建层级树：上层每列 → 下层对应子列
        header_tree: dict[int, list[int]] = {}

        for parent_ri in range(header_rows - 1):
            child_ri = parent_ri + 1
            parent_row = table_data[parent_ri]
            child_row = table_data[child_ri]

            parent_cols = len(parent_row)
            child_cols = len(child_row)

            # 使用 colspan 信息（如果有）确定父子关系
            child_idx = 0
            for pi in range(parent_cols):
                cs = 1
                if colspans and parent_ri < len(colspans) and pi < len(colspans[parent_ri]):
                    cs = colspans[parent_ri][pi]
                if cs == 0:
                    continue

                children = list(range(child_idx, min(child_idx + cs, child_cols)))
                if children:
                    header_tree[pi] = children
                child_idx += cs

        return header_rows, header_tree

    @classmethod
    def _build_table_html_with_headers(
        cls,
        table_data: list[list[str]],
        colspans: list[list[int]] | None = None,
        rowspans: list[list[int]] | None = None,
        header_rows: int = 1,
    ) -> str:
        """构建带多级表头标记的 HTML 表格。

        header_rows > 1 时，前 header_rows 行均使用 <th>，
        并添加 data-header-level 属性标记层级，便于前端渲染。
        """
        if not table_data:
            return '<div class="kb-table-wrapper"><table class="kb-table"></table></div>'

        nrows = len(table_data)
        ncols = max((len(r) for r in table_data), default=0)
        parts = ['<div class="kb-table-wrapper"><table class="kb-table">']

        # thead: 多级表头行
        if header_rows > 0:
            parts.append("<thead>")
            for i in range(min(header_rows, nrows)):
                row = table_data[i]
                header_level = header_rows - i - 1  # 0 = 最底层表头, N-1 = 最顶层
                cells_parts: list[str] = []
                for j in range(ncols):
                    if colspans and i < len(colspans) and j < len(colspans[i]) and colspans[i][j] == 0:
                        continue
                    if rowspans and i < len(rowspans) and j < len(rowspans[i]) and rowspans[i][j] == 0:
                        continue
                    attrs = f' data-header-level="{header_level}"'
                    if colspans and i < len(colspans) and j < len(colspans[i]) and colspans[i][j] > 1:
                        attrs += f' colspan="{colspans[i][j]}"'
                    if rowspans and i < len(rowspans) and j < len(rowspans[i]) and rowspans[i][j] > 1:
                        attrs += f' rowspan="{rowspans[i][j]}"'
                    content = str(row[j]).strip() if j < len(row) and row[j] else ""
                    cells_parts.append(f"<th{attrs}>{content}</th>")
                parts.append(f"<tr>{''.join(cells_parts)}</tr>")
            parts.append("</thead>")

        # tbody: 数据行
        if nrows > header_rows:
            parts.append("<tbody>")
            for i in range(header_rows, nrows):
                row = table_data[i]
                cells_parts: list[str] = []
                for j in range(ncols):
                    if colspans and i < len(colspans) and j < len(colspans[i]) and colspans[i][j] == 0:
                        continue
                    if rowspans and i < len(rowspans) and j < len(rowspans[i]) and rowspans[i][j] == 0:
                        continue
                    attrs = ""
                    if colspans and i < len(colspans) and j < len(colspans[i]) and colspans[i][j] > 1:
                        attrs += f' colspan="{colspans[i][j]}"'
                    if rowspans and i < len(rowspans) and j < len(rowspans[i]) and rowspans[i][j] > 1:
                        attrs += f' rowspan="{rowspans[i][j]}"'
                    content = str(row[j]).strip() if j < len(row) and row[j] else ""
                    cells_parts.append(f"<td{attrs}>{content}</td>")
                parts.append(f"<tr>{''.join(cells_parts)}</tr>")
            parts.append("</tbody>")

        parts.append("</table></div>")
        return "\n".join(parts)

    # ── 合并单元格检测 ──────────────────────────────────────

    @classmethod
    def _detect_merged_cells(
        cls,
        table_data: list[list[str]],
        cell_bboxes: list[list[tuple[float, float, float, float] | None]] | None = None,
        col_x_boundaries: list[float] | None = None,
        row_y_boundaries: list[float] | None = None,
    ) -> tuple[list[list[int]], list[list[int]]]:
        """检测表格中的合并单元格，返回 (colspans, rowspans) 矩阵。

        当提供 cell_bboxes（来自 pdfplumber Table.cells）时使用精确几何检测；
        否则回退到基于内容的启发式检测。
        """
        if not table_data:
            return [], []

        rows = len(table_data)
        cols = max((len(r) for r in table_data), default=0)

        if cell_bboxes and col_x_boundaries and row_y_boundaries:
            return cls._detect_merged_from_geometry(
                table_data, cell_bboxes, col_x_boundaries, row_y_boundaries
            )
        return cls._detect_merged_from_content(table_data, rows, cols)

    @classmethod
    def _detect_merged_from_geometry(
        cls,
        table_data: list[list[str]],
        cell_bboxes: list[list[tuple[float, float, float, float] | None]],
        col_x_boundaries: list[float],
        row_y_boundaries: list[float],
    ) -> tuple[list[list[int]], list[list[int]]]:
        """通过单元格外接框精确检测合并单元格。

        算法：对每个非空单元格，计算其 bbox 右/下边界跨越了几列几行。
        被合并覆盖的单元格标记为 span=0（前端跳过渲染）。
        """
        rows = len(table_data)
        cols = max((len(r) for r in table_data), default=0)
        colspans = [[1] * cols for _ in range(rows)]
        rowspans = [[1] * cols for _ in range(rows)]

        for ri in range(min(rows, len(cell_bboxes))):
            row_cells = cell_bboxes[ri]
            for ci in range(min(cols, len(row_cells))):
                bbox = row_cells[ci]
                if bbox is None:
                    continue

                x0, _y0, x1, y1 = bbox

                # 检测 colspan：右边界跨越了几个列分隔线
                end_col = ci
                for c in range(ci + 1, len(col_x_boundaries)):
                    if x1 <= col_x_boundaries[c] + 2:  # 2pt 容差
                        break
                    end_col = c
                cs = end_col - ci + 1
                if cs > 1:
                    colspans[ri][ci] = cs
                    for s in range(1, cs):
                        if ci + s < cols:
                            colspans[ri][ci + s] = 0

                # 检测 rowspan：下边界跨越了几个行分隔线
                end_row = ri
                for r in range(ri + 1, len(row_y_boundaries)):
                    if y1 <= row_y_boundaries[r] + 2:
                        break
                    end_row = r
                rs = end_row - ri + 1
                if rs > 1:
                    rowspans[ri][ci] = rs
                    for s in range(1, rs):
                        if ri + s < rows:
                            rowspans[ri + s][ci] = 0

        return colspans, rowspans

    @classmethod
    def _detect_merged_from_content(
        cls, table_data: list[list[str]], rows: int, cols: int
    ) -> tuple[list[list[int]], list[list[int]]]:
        """基于内容模式启发式检测合并单元格（无几何信息时的回退方案）。

        规则：
        - colspan: 非空单元格右侧连续空单元格（且这些空单元格下方有内容→确认是独立列）
        - rowspan: 非空单元格下方连续空单元格（且这些行有其他列的内容→确认是独立行）
        """
        colspans = [[1] * cols for _ in range(rows)]
        rowspans = [[1] * cols for _ in range(rows)]

        # 归一化补齐不等宽行
        norm: list[list[str]] = []
        for row in table_data:
            padded = list(row) + [""] * (cols - len(row))
            norm.append([str(c).strip() if c else "" for c in padded])

        # ── Colspan ──
        for ri in range(rows):
            ci = 0
            while ci < cols:
                if not norm[ri][ci]:
                    ci += 1
                    continue
                span = 1
                for next_ci in range(ci + 1, cols):
                    if norm[ri][next_ci]:
                        break
                    below_has = any(norm[r][next_ci] for r in range(ri + 1, rows))
                    if below_has:
                        span += 1
                    else:
                        break
                if span > 1:
                    colspans[ri][ci] = span
                    for s in range(1, span):
                        if ci + s < cols:
                            colspans[ri][ci + s] = 0
                ci += span

        # ── Rowspan ──
        for ci in range(cols):
            ri = 0
            while ri < rows:
                if colspans[ri][ci] == 0:
                    ri += 1
                    continue
                if not norm[ri][ci]:
                    ri += 1
                    continue
                span = 1
                for next_ri in range(ri + 1, rows):
                    if norm[next_ri][ci]:
                        break
                    row_has = any(norm[next_ri][c] for c in range(cols) if c != ci)
                    if row_has:
                        span += 1
                    else:
                        break
                if span > 1:
                    rowspans[ri][ci] = span
                    for s in range(1, span):
                        if ri + s < rows:
                            rowspans[ri + s][ci] = 0
                ri += span

        return colspans, rowspans

    @classmethod
    def _pdfplumber_table_cell_info(
        cls, table_obj: object
    ) -> tuple[
        list[list[tuple[float, float, float, float] | None]],
        list[float],
        list[float],
    ]:
        """从 pdfplumber Table 对象提取单元格坐标网格。

        Returns:
            (cell_bboxes, col_x_boundaries, row_y_boundaries)
        """
        cell_bboxes: list[list[tuple[float, float, float, float] | None]] = []
        col_boundaries_set: set[float] = set()
        row_boundaries_set: set[float] = set()

        try:
            for row_cells in table_obj.cells:
                row_bboxes: list[tuple[float, float, float, float] | None] = []
                for cell in row_cells:
                    if cell is not None:
                        bbox = (cell[0], cell[1], cell[2], cell[3])
                        row_bboxes.append(bbox)
                        col_boundaries_set.add(cell[0])
                        col_boundaries_set.add(cell[2])
                        row_boundaries_set.add(cell[1])
                        row_boundaries_set.add(cell[3])
                    else:
                        row_bboxes.append(None)
                if row_bboxes:
                    cell_bboxes.append(row_bboxes)
        except Exception:
            return [], [], []

        return (
            cell_bboxes,
            sorted(col_boundaries_set),
            sorted(row_boundaries_set),
        )

    @staticmethod
    def _table_to_markdown(
        table_data: list[list[str]],
        colspans: list[list[int]] | None = None,
        rowspans: list[list[int]] | None = None,
    ) -> str:
        """二维列表 → Markdown 表格。委托给独立模块。"""
        from src.services.document_processors.table_renderer import table_to_markdown
        return table_to_markdown(table_data, colspans, rowspans)

    @staticmethod
    def _table_to_html(
        table_data: list[list[str]],
        colspans: list[list[int]] | None = None,
        rowspans: list[list[int]] | None = None,
    ) -> str:
        """将表格数据转为 HTML。委托给独立模块。"""
        from src.services.document_processors.table_renderer import table_to_html
        return table_to_html(table_data, colspans, rowspans)

