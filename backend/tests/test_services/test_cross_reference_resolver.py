"""CrossReferenceResolver 图文交叉引用解析器单元测试。"""

import pytest

from src.services.chunking.data_models import StructuredBlock
from src.services.cross_reference_resolver import (
    CrossReference,
    CrossReferenceResolver,
    _normalize_ref_id,
)


@pytest.mark.unit
def test_normalize_ref_id_dash_to_dot() -> None:
    assert _normalize_ref_id("3-2") == "3.2"
    assert _normalize_ref_id("1.1") == "1.1"


@pytest.mark.unit
def test_normalize_ref_id_preserves_plain() -> None:
    assert _normalize_ref_id("5") == "5"
    assert _normalize_ref_id("  100  ") == "100"


class TestCrossReferenceResolver:
    @pytest.mark.unit
    def test_empty_blocks(self) -> None:
        result = CrossReferenceResolver.resolve([])
        assert result == []

    @pytest.mark.unit
    def test_no_figures_or_tables(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="如图3-1所示", page_number=1),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].image_refs is None

    @pytest.mark.unit
    def test_chinese_image_ref_matched(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="如图3-1所示，系统架构清晰。", page_number=1),
            StructuredBlock(
                block_type="image", content="图3-1 系统架构图",
                page_number=1, image_caption="图3-1 系统架构图",
            ),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].image_refs is not None
        assert any("image" in ref for ref in result[0].image_refs)
        assert "3.1" in result[0].image_refs[0]

    @pytest.mark.unit
    def test_chinese_table_ref_matched(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="实验结果见表2-1。", page_number=1),
            StructuredBlock(
                block_type="table", content="表2-1 实验结果",
                page_number=2, table_caption="表2-1 实验结果",
            ),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].table_refs is not None
        assert any("table" in ref for ref in result[0].table_refs)

    @pytest.mark.unit
    def test_english_figure_ref_matched(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="As shown in Figure 3.2, ...", page_number=1),
            StructuredBlock(
                block_type="image", content="Figure 3.2 Architecture",
                page_number=1, image_caption="Figure 3.2 Architecture",
            ),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].image_refs is not None
        assert "3.2" in result[0].image_refs[0]

    @pytest.mark.unit
    def test_english_table_ref_matched(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="See Table 1 for details.", page_number=1),
            StructuredBlock(
                block_type="table", content="Table 1 Results",
                page_number=1, table_caption="Table 1 Results",
            ),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].table_refs is not None
        assert "1" in result[0].table_refs[0]

    @pytest.mark.unit
    def test_no_match_when_caption_absent(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="如图5-5所示", page_number=1),
            StructuredBlock(
                block_type="image", content="Some image",
                page_number=1, image_caption="图5-3 其他",
            ),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].image_refs is None

    @pytest.mark.unit
    def test_multiple_refs_in_single_block(self) -> None:
        blocks = [
            StructuredBlock(
                block_type="text",
                content="如图2-1所示，以及参见图2-2。",
                page_number=1,
            ),
            StructuredBlock(
                block_type="image", content="图2-1 流程图A",
                page_number=1, image_caption="图2-1 流程图A",
            ),
            StructuredBlock(
                block_type="image", content="图2-2 流程图B",
                page_number=1, image_caption="图2-2 流程图B",
            ),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        refs = result[0].image_refs or []
        assert len(refs) == 2

    @pytest.mark.unit
    def test_non_text_blocks_skipped(self) -> None:
        blocks = [
            StructuredBlock(block_type="table", content="图3-1 表格中的引用", page_number=1),
        ]
        result = CrossReferenceResolver.resolve(blocks)
        assert result[0].image_refs is None

    @pytest.mark.unit
    def test_extract_figure_number_chinese(self) -> None:
        assert CrossReferenceResolver._extract_figure_number("图3-2 系统架构") == "3-2"
        assert CrossReferenceResolver._extract_figure_number("Figure 5 Architecture") == "5"

    @pytest.mark.unit
    def test_extract_figure_number_none(self) -> None:
        assert CrossReferenceResolver._extract_figure_number("系统架构图") is None

    @pytest.mark.unit
    def test_extract_table_number(self) -> None:
        assert CrossReferenceResolver._extract_table_number("表1 实验结果") == "1"
        assert CrossReferenceResolver._extract_table_number("Table 3.1 Results") == "3.1"

    @pytest.mark.unit
    def test_cross_reference_dataclass(self) -> None:
        cr = CrossReference(
            source_block_idx=0,
            ref_type="image",
            ref_text="图3-1",
            ref_number="3.1",
            target_caption="图3-1 架构图",
            target_page=2,
        )
        assert cr.ref_type == "image"
        assert cr.target_page == 2
