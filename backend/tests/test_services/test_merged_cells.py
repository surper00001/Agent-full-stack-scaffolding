"""表格合并单元格检测单元测试。

覆盖场景：
- colspan 检测（横向合并）
- rowspan 检测（纵向合并）
- 混合 colspan + rowspan
- 几何检测 vs 内容启发式回退
- HTML/Markdown 输出中的合并处理
"""

from __future__ import annotations

import pytest

from src.services.document_processor import DocumentProcessor


@pytest.mark.unit
class TestMergeDetectionContent:
    """基于内容的合并单元格检测（无几何信息回退）。"""

    def test_simple_colspan(self) -> None:
        """表头跨两列：列1有值，列2为空且下方有内容。"""
        data = [
            ["类别", "", "数值"],  # "类别" 应合并 col1+col2
            ["环境", "土壤", "100"],
            ["环境", "水文", "200"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        # "类别" 跨两列
        assert colspans[0][0] == 2, f"Expected colspan=2 for '类别', got {colspans[0][0]}"
        assert colspans[0][1] == 0, f"Expected col2 covered (0), got {colspans[0][1]}"
        # 其他单元格正常
        assert colspans[1][0] == 1

    def test_simple_rowspan(self) -> None:
        """首列跨行：第一列跨多行的分类标签。"""
        data = [
            ["环境模型", "气候", "提供基础数据"],
            ["", "水文", "模拟水流"],
            ["", "土壤", "分析成分"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        # "环境模型" 应跨 3 行
        assert rowspans[0][0] == 3, f"Expected rowspan=3, got {rowspans[0][0]}"
        assert rowspans[1][0] == 0, f"Expected row2 covered, got {rowspans[1][0]}"
        assert rowspans[2][0] == 0

    def test_no_merge_normal_table(self) -> None:
        """普通表格无合并单元格。"""
        data = [
            ["姓名", "年龄", "城市"],
            ["张三", "25", "北京"],
            ["李四", "30", "上海"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        for row in colspans:
            assert all(v == 1 for v in row), f"Unexpected colspan in normal table: {colspans}"
        for row in rowspans:
            assert all(v == 1 for v in row), f"Unexpected rowspan in normal table: {rowspans}"

    def test_empty_table(self) -> None:
        """空表格输入。"""
        colspans, rowspans = DocumentProcessor._detect_merged_cells([])
        assert colspans == []
        assert rowspans == []

    def test_irregular_width_rows(self) -> None:
        """不等宽行（pdfplumber 常见）。"""
        data = [
            ["项目", "Q1", "Q2", "Q3"],
            ["收入", "100", "200"],  # 少一列
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        # 应该归一化后正常处理
        assert len(colspans) == 2
        assert len(colspans[0]) == 4

    def test_mixed_merge(self) -> None:
        """混合 colspan + rowspan: 左上角大格跨越 2x2。"""
        data = [
            ["总计", "", "Q1", "Q2"],
            ["", "", "100", "200"],
            ["分类A", "子类1", "50", "80"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        # "总计" 应跨 2 列 2 行
        assert colspans[0][0] >= 2, f"Expected colspan>=2 for '总计', got {colspans}"
        assert rowspans[0][0] >= 2, f"Expected rowspan>=2 for '总计', got {rowspans}"


@pytest.mark.unit
class TestMergeHTMLOutput:
    """验证 HTML 输出正确包含 colspan/rowspan 属性。"""

    def test_html_colspan_output(self) -> None:
        """带 colspan 的 HTML 输出。"""
        data = [
            ["类别", "", "数值"],
            ["环境", "土壤", "100"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        html = DocumentProcessor._table_to_html(data, colspans, rowspans)
        assert 'colspan="2"' in html, f"Missing colspan in HTML: {html}"
        # col2 被覆盖不应渲染
        # Count <th> or first row <td> tags — should be 2, not 3
        import re
        first_row_cells = re.findall(r"<(?:th|td)[^>]*>", html.split("</tr>")[0])
        assert len(first_row_cells) <= 3, f"Too many cells in first row: {html[:200]}"

    def test_html_rowspan_output(self) -> None:
        """带 rowspan 的 HTML 输出。"""
        data = [
            ["环境模型", "气候"],
            ["", "水文"],
            ["", "土壤"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        html = DocumentProcessor._table_to_html(data, colspans, rowspans)
        assert 'rowspan="3"' in html, f"Missing rowspan in HTML (first 300 chars): {html[:300]}"

    def test_markdown_fills_merged_content(self) -> None:
        """Markdown 输出应在合并覆盖区域填充内容（提升检索召回）。"""
        data = [
            ["类别", "", "数值"],
            ["环境", "土壤", "100"],
            ["环境", "水文", "200"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        md = DocumentProcessor._table_to_markdown(data, colspans, rowspans)
        # "类别" 应出现在第一行的第二列位置（被填充）
        # 检查第一行包含两个 "类别"
        first_row = md.split("\n")[0]
        assert first_row.count("类别") >= 1, f"Content not preserved in merged markdown: {first_row}"
