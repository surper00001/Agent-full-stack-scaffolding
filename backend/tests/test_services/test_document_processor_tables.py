"""文档处理器表格校验与续表单元测试。"""

from __future__ import annotations

import pytest

from src.services.chunking_service import StructuredBlock
from src.services.document_processor import DocumentProcessor


@pytest.mark.unit
class TestIsValidTable:
    def test_valid_2x2_table(self) -> None:
        data = [
            ["姓名", "年龄"],
            ["张三", "25"],
            ["李四", "30"],
        ]
        assert DocumentProcessor._is_valid_table(data) is True

    def test_valid_academic_three_line_table(self) -> None:
        """三线表：多列、多行、中英文表头。"""
        data = [
            ["类别", "组成要素", "作用与功能"],
            ["环境模型", "气候/水文/土壤/地形", "提供基础数据"],
            ["森林生长模型", "单木/林分/经验统计", "预测发展趋势"],
            ["经营决策模型", "造林/采伐/更新", "指导实际经营"],
        ]
        assert DocumentProcessor._is_valid_table(data) is True

    def test_reject_single_column_list(self) -> None:
        data = [
            ["第一项说明文字"],
            ["第二项说明文字"],
            ["第三项说明文字"],
        ]
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_too_few_rows(self) -> None:
        assert DocumentProcessor._is_valid_table([["a", "b"]]) is False

    def test_reject_mostly_empty_cells(self) -> None:
        data = [
            ["", ""],
            ["", ""],
            ["x", ""],
        ]
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_single_non_empty_per_row(self) -> None:
        data = [
            ["段落一", ""],
            ["段落二", ""],
            ["段落三", ""],
            ["段落四", ""],
        ]
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_duplicate_long_text_across_columns(self) -> None:
        long_text = "这是一段很长的重复说明文字" * 3
        data = [
            [long_text, long_text],
            [long_text, long_text],
        ]
        assert DocumentProcessor._is_valid_table(data) is False


@pytest.mark.unit
class TestTableIndicators:
    def test_detect_chinese_table_caption(self) -> None:
        text = "第 11 期\n表 2 森林经营数字孪生机理模型\nTab. 2 Mechanistic models"
        assert DocumentProcessor._text_has_table_indicator(text) is True

    def test_detect_english_table_caption(self) -> None:
        text = "Table 3 Summary of experimental results"
        assert DocumentProcessor._text_has_table_indicator(text) is True

    def test_detect_continued_table(self) -> None:
        assert DocumentProcessor._is_continued_table_caption("表2（续）") is True
        assert DocumentProcessor._is_continued_table_caption("Table 2 (continued)") is True


@pytest.mark.unit
class TestMergeContinuedTables:
    def test_merge_continued_table_rows(self) -> None:
        proc = DocumentProcessor()
        blocks = [
            StructuredBlock(
                block_type="table",
                content="[表格] 表2 机理模型",
                page_number=5,
                table_caption="表2 森林经营数字孪生机理模型",
                table_data=[
                    ["类别", "组成要素", "作用与功能"],
                    ["环境模型", "气候模型", "基础数据"],
                ],
            ),
            StructuredBlock(
                block_type="table",
                content="[表格] 表2（续）",
                page_number=6,
                table_caption="表2（续）",
                table_data=[
                    ["类别", "组成要素", "作用与功能"],
                    ["经营决策模型", "造林/采伐", "指导经营"],
                ],
            ),
        ]
        merged = proc._merge_continued_tables(blocks)
        tables = [b for b in merged if b.block_type == "table"]
        assert len(tables) == 1
        assert len(tables[0].table_data or []) == 3
        assert "经营决策模型" in (tables[0].table_data or [])[2][0]
