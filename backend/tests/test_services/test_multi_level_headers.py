"""多级表头检测单元测试。

覆盖场景：
- 单级表头（普通表格）
- 两级表头（年度 → 季度）
- 三级表头（大类 → 小类 → 指标）
- 非表头行（数据行含数字）不误判为表头
"""

from __future__ import annotations

import pytest

from src.services.document_processor import DocumentProcessor


@pytest.mark.unit
class TestMultiLevelHeaders:
    def test_single_level_header(self) -> None:
        """普通单级表头。"""
        data = [
            ["姓名", "年龄", "城市"],
            ["张三", "25", "北京"],
            ["李四", "30", "上海"],
        ]
        header_rows, tree = DocumentProcessor._detect_multi_level_headers(data)
        assert header_rows == 1, f"Expected 1 header row, got {header_rows}"
        assert tree == {}, f"Expected empty tree for single header, got {tree}"

    def test_two_level_header(self) -> None:
        """两级表头：年度 → 季度。"""
        data = [
            ["2024年度", "", "", "2025年度", "", ""],
            ["Q1", "Q2", "Q3", "Q4", "Q1", "Q2"],
            ["100", "200", "150", "180", "120", "210"],
        ]
        # 先检测合并
        colspans, _ = DocumentProcessor._detect_merged_cells(data)
        header_rows, tree = DocumentProcessor._detect_multi_level_headers(data, colspans)
        assert header_rows == 2, f"Expected 2 header rows, got {header_rows}"
        # 第0行：两列合并，每列跨3个子列
        assert len(tree) >= 1, f"Expected header tree, got {tree}"

    def test_two_level_without_merge_detection(self) -> None:
        """两级表头但未提供 colspan —— 仍应检测出 2 行表头。"""
        data = [
            ["收入", "支出"],
            ["产品A", "产品B", "工资", "材料"],
            ["100", "200", "50", "30"],
        ]
        header_rows, _ = DocumentProcessor._detect_multi_level_headers(data)
        assert header_rows == 2, f"Expected 2 header rows, got {header_rows}"

    def test_no_header_label_rows(self) -> None:
        """无表头的纯数据表（第一行就是数字）。"""
        data = [
            ["100", "200", "150"],
            ["300", "400", "350"],
        ]
        header_rows, _ = DocumentProcessor._detect_multi_level_headers(data)
        # "100" 是短文本但不是典型标签，但算法可能仍判为1行表头
        # 只要不是 > 1 的多级表头即可
        assert header_rows <= 1

    def test_data_rows_not_mistaken_as_headers(self) -> None:
        """数据行中的长文本不应被误判为表头。"""
        data = [
            ["科目", "说明", "金额"],
            ["办公费", "日常办公用品采购及设备维护费用", "5000"],
            ["差旅费", "员工出差交通住宿餐饮等费用报销", "12000"],
        ]
        header_rows, _ = DocumentProcessor._detect_multi_level_headers(data)
        # 第二行虽然有短标签"办公费"，但"说明"列是长文本 → 不应算表头
        assert header_rows == 1, f"Data row mistaken as header: got {header_rows}"


@pytest.mark.unit
class TestMultiLevelHTMLOutput:
    def test_html_has_thead_tbody(self) -> None:
        """多级表头 HTML 应包含 <thead> 和 <tbody>。"""
        data = [
            ["2024年度", "", "2025年度", ""],
            ["Q1", "Q2", "Q3", "Q4"],
            ["100", "200", "150", "180"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        header_rows, _ = DocumentProcessor._detect_multi_level_headers(data, colspans)

        html = DocumentProcessor._build_table_html_with_headers(
            data, colspans, rowspans, header_rows
        )
        assert "<thead>" in html, f"Missing thead: {html[:300]}"
        assert "<tbody>" in html, f"Missing tbody: {html[:300]}"
        assert 'data-header-level=' in html, f"Missing header-level attr: {html[:300]}"
        # 顶层表头应标记为 data-header-level="1"
        assert 'data-header-level="1"' in html or 'data-header-level="0"' in html

    def test_single_header_no_thead(self) -> None:
        """单级表头不使用专用的带 thead HTML（由 _table_to_html 处理）。"""
        # 单级表头时 header_rows=1 会被条件跳过 _build_table_html_with_headers
        data = [
            ["姓名", "年龄"],
            ["张三", "25"],
        ]
        colspans, rowspans = DocumentProcessor._detect_merged_cells(data)
        header_rows, _ = DocumentProcessor._detect_multi_level_headers(data, colspans)
        assert header_rows == 1
        # _table_to_html 不输出 thead（向后兼容）
        html = DocumentProcessor._table_to_html(data, colspans, rowspans)
        assert "<thead>" not in html
