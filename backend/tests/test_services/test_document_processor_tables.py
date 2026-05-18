"""文档处理器表格校验、续表与 VLM 表格提取单元测试。"""

from __future__ import annotations

import pytest

from src.services.chunking_service import StructuredBlock
from src.services.document_processor import DocumentProcessor
from src.services.vlm_service import VLMService


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

    def test_reject_separator_lines(self) -> None:
        """分隔线（如 "────" "────"）不应识别为表格。"""
        data = [
            ["──────", "────────"],
            ["──────", "────────"],
            ["──────", "────────"],
        ]
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_single_separator_line(self) -> None:
        """夹杂分隔线的伪表格。"""
        data = [
            ["姓名", "年龄"],
            ["──────", "────"],
            ["张三", "25"],
        ]
        # 一行分隔线占 1/3 = 33% > 25% → 应拒绝
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_prose_aligned_as_table(self) -> None:
        """对齐的自然语言段落不应识别为表格。"""
        data = [
            ["这是一个关于森林经营的详细说明文字段落。", "第二个列的文本也是自然语言。这是对表格的补充说明。"],
            ["表格中的数据表明近十年经营面积逐步增加。", "随着政策的变化，造林面积也在不断变化中。"],
            ["从整体趋势来看森林生长模型预测。", "经营决策模型的参数需要定期校准和更新。"],
        ]
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_all_columns_long_text(self) -> None:
        """每列都是长文本（平均 >30 字符）——对齐散文而非表格。"""
        data = [
            ["这是一段较长的说明文字内容段落" * 3, "这是一段较长的说明文字内容" * 3],
            ["这是另一段较长的文字信息描述" * 3, "这是另一段较长的文字内容描述" * 3],
            ["还有一段更长的描述性文本段落" * 3, "还有一段更长的描述性文本内容" * 3],
        ]
        assert DocumentProcessor._is_valid_table(data) is False

    def test_reject_inconsistent_column_counts(self) -> None:
        """列数不稳定的「表格」（行间差 >1 列）。"""
        data = [
            ["a", "b", "c"],
            ["d", "e"],
            ["f", "g", "h", "i"],
        ]
        assert DocumentProcessor._is_valid_table(data) is False


@pytest.mark.unit
class TestTextHasTableIndicator:
    def test_text_with_caption_returns_true(self) -> None:
        text = "表 1 实验结果汇总\n姓名 年龄\n张三 25"
        assert DocumentProcessor._text_has_table_indicator(text) is True

    def test_multi_column_with_numbers_returns_true(self) -> None:
        """有数字列的多列对齐文本 → 可能是表格。"""
        text = (
            "姓名          年龄    城市\n"
            "张三          25     北京\n"
            "李四          30     上海\n"
            "王五          28     广州\n"
            "赵六          35     深圳\n"
            "孙七          22     杭州\n"
        )
        assert DocumentProcessor._text_has_table_indicator(text) is True

    def test_multi_column_no_numbers_returns_false(self) -> None:
        """仅有多列对齐但无数字列 → 不是表格（可能是列表/散文）。"""
        text = (
            "第一项       说明文字       备注\n"
            "第二项       说明文字       备注\n"
            "第三项       说明文字       备注\n"
            "第四项       说明文字       备注\n"
            "第五项       说明文字       备注\n"
        )
        assert DocumentProcessor._text_has_table_indicator(text) is False

    def test_few_lines_fallback_returns_false(self) -> None:
        """少于 5 行对齐文本 → 不判定为表格。"""
        text = "a       b       c\nd       e       f\ng       h       i"
        assert DocumentProcessor._text_has_table_indicator(text) is False


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


@pytest.mark.unit
class TestVlmParseMarkdownTables:
    """VLM 响应中 Markdown 表格解析测试。"""

    def test_parse_single_table(self) -> None:
        text = (
            "| 姓名 | 年龄 | 城市 |\n"
            "| --- | --- | --- |\n"
            "| 张三 | 25 | 北京 |\n"
            "| 李四 | 30 | 上海 |\n"
        )
        tables = VLMService._parse_markdown_tables(text)
        assert len(tables) == 1
        assert tables[0] == [
            ["姓名", "年龄", "城市"],
            ["张三", "25", "北京"],
            ["李四", "30", "上海"],
        ]

    def test_parse_multiple_tables(self) -> None:
        text = (
            "| A | B |\n"
            "| --- | --- |\n"
            "| 1 | 2 |\n"
            "---TABLE---\n"
            "| X | Y | Z |\n"
            "| --- | --- | --- |\n"
            "| a | b | c |\n"
        )
        tables = VLMService._parse_markdown_tables(text)
        assert len(tables) == 2
        assert tables[0] == [["A", "B"], ["1", "2"]]
        assert tables[1] == [["X", "Y", "Z"], ["a", "b", "c"]]

    def test_skip_separator_variants(self) -> None:
        """对齐列分隔符变体（:---, ---:, :---:）应正确识别。"""
        text = (
            "| 名称 | 数量 |\n"
            "| :--- | ---: |\n"
            "| 苹果 | 10 |\n"
        )
        tables = VLMService._parse_markdown_tables(text)
        assert len(tables) == 1
        assert tables[0][1] == ["苹果", "10"]

    def test_handle_trailing_leading_pipes(self) -> None:
        """带有前后 | 的标准 Markdown 表格格式。"""
        text = (
            "| Col1 | Col2 |\n"
            "|------|------|\n"
            "| val1 | val2 |\n"
        )
        tables = VLMService._parse_markdown_tables(text)
        assert len(tables) == 1
        assert tables[0][0] == ["Col1", "Col2"]

    def test_ignore_non_table_text(self) -> None:
        """表格前有说明文字应被忽略。"""
        text = (
            "以下是识别出的表格：\n"
            "| 编号 | 描述 |\n"
            "| --- | --- |\n"
            "| 001 | 测试 |\n"
        )
        tables = VLMService._parse_markdown_tables(text)
        assert len(tables) == 1
        assert tables[0][0] == ["编号", "描述"]

    def test_vlm_extract_tables_no_tables(self) -> None:
        """空图片或无表格页应返回空列表。"""
        tables, err = VLMService().extract_tables(b"fake_image_data")
        assert tables == []  # VLM 未启用时直接返回空

    def test_chinese_table_parsing(self) -> None:
        """中文表格解析。"""
        text = (
            "| 类别 | 组成要素 | 作用与功能 |\n"
            "| --- | --- | --- |\n"
            "| 环境模型 | 气候/水文/土壤/地形 | 提供基础数据 |\n"
            "| 森林生长模型 | 单木/林分/经验统计 | 预测发展趋势 |\n"
        )
        tables = VLMService._parse_markdown_tables(text)
        assert len(tables) == 1
        assert len(tables[0]) == 3  # header + 2 data rows
        assert "环境模型" in tables[0][1]
