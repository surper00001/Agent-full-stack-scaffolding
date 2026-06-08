"""表格渲染工具 — Markdown / HTML 格式转换。

从 TableUtilsMixin 提取的纯函数，无类状态依赖。
"""

from __future__ import annotations


def table_to_markdown(
    table_data: list[list[str]],
    colspans: list[list[int]] | None = None,
    rowspans: list[list[int]] | None = None,
) -> str:
    """二维列表 → Markdown 表格，合并单元格内容在覆盖区域重复填充（提升检索召回）。"""
    if not table_data:
        return ""
    nrows = len(table_data)
    ncols = max((len(r) for r in table_data), default=0)

    # 构建填充矩阵：合并单元格的内容复制到被覆盖的格子
    filled: list[list[str]] = []
    for i, row in enumerate(table_data):
        filled_row: list[str] = []
        for j in range(ncols):
            cell = str(row[j]).replace("\n", " ").replace("|", "\\|").strip() if j < len(row) and row[j] else ""
            # 如果该单元格被左侧合并覆盖(colspan=0)或被上方合并覆盖(rowspan=0)，从源头复制内容
            if colspans and i < len(colspans) and j < len(colspans[i]) and colspans[i][j] == 0:
                for sj in range(j - 1, -1, -1):
                    if colspans[i][sj] > 0 and sj + colspans[i][sj] > j:
                        src_val = str(table_data[i][sj]).replace("\n", " ").replace("|", "\\|").strip() if i < len(table_data) and sj < len(table_data[i]) and table_data[i][sj] else ""
                        cell = src_val
                        break
            if rowspans and i < len(rowspans) and j < len(rowspans[i]) and rowspans[i][j] == 0:
                for si in range(i - 1, -1, -1):
                    if si < len(rowspans) and j < len(rowspans[si]) and rowspans[si][j] > 0 and si + rowspans[si][j] > i:
                        src_val = str(table_data[si][j]).replace("\n", " ").replace("|", "\\|").strip() if si < len(table_data) and j < len(table_data[si]) and table_data[si][j] else ""
                        cell = src_val
                        break
            if not cell:
                cell = ""
            filled_row.append(cell)
        filled.append(filled_row)

    rows = []
    for i, row in enumerate(filled):
        rows.append("| " + " | ".join(row) + " |")
        if i == 0 and len(filled) > 1:
            rows.append("| " + " | ".join(["---"] * len(row)) + " |")
    return "\n".join(rows)


def table_to_html(
    table_data: list[list[str]],
    colspans: list[list[int]] | None = None,
    rowspans: list[list[int]] | None = None,
) -> str:
    """将表格数据转为 HTML，可选支持合并单元格。

    colspans: 与 table_data 同形的二维列表，每格为 colspan 值（默认 1）
    rowspans: 与 table_data 同形的二维列表，每格为 rowspan 值（默认 1）
    """
    if not table_data:
        return '<div class="kb-table-wrapper"><table class="kb-table"></table></div>'
    parts = ['<div class="kb-table-wrapper"><table class="kb-table">']
    for i, row in enumerate(table_data):
        tag = "th" if i == 0 else "td"
        cells_parts: list[str] = []
        for j, cell in enumerate(row):
            # 跳过被合并覆盖的单元格（colspan=0 或 rowspan=0）
            if colspans and i < len(colspans) and j < len(colspans[i]) and colspans[i][j] == 0:
                continue
            if rowspans and i < len(rowspans) and j < len(rowspans[i]) and rowspans[i][j] == 0:
                continue
            attrs = ""
            if colspans and i < len(colspans) and j < len(colspans[i]):
                cs = colspans[i][j]
                if cs > 1:
                    attrs += f' colspan="{cs}"'
            if rowspans and i < len(rowspans) and j < len(rowspans[i]):
                rs = rowspans[i][j]
                if rs > 1:
                    attrs += f' rowspan="{rs}"'
            content = str(cell).strip() if cell else ""
            cells_parts.append(f"<{tag}{attrs}>{content}</{tag}>")
        parts.append(f"<tr>{''.join(cells_parts)}</tr>")
    parts.append("</table></div>")
    return "\n".join(parts)
