"""FootnoteResolver 脚注/尾注解析器单元测试。"""

import pytest

from src.services.chunking.data_models import StructuredBlock
from src.services.document_processors.layout import LayoutTag
from src.services.footnote_resolver import (
    FootnoteResolver,
    _normalize_footnote_marker,
)


@pytest.mark.unit
def test_normalize_superscript_numbers() -> None:
    assert _normalize_footnote_marker("¹") == "1"
    assert _normalize_footnote_marker("²³") == "23"


@pytest.mark.unit
def test_normalize_circled_numbers() -> None:
    assert _normalize_footnote_marker("①") == "1"
    assert _normalize_footnote_marker("⑩") == "10"


@pytest.mark.unit
def test_normalize_bracket_numbers() -> None:
    assert _normalize_footnote_marker("[1]") == "1"
    assert _normalize_footnote_marker("[12]") == "12"


@pytest.mark.unit
def test_normalize_preserves_plain() -> None:
    assert _normalize_footnote_marker("*") == "*"
    assert _normalize_footnote_marker("1.") == "1."


class TestFootnoteResolver:
    @pytest.mark.unit
    def test_empty_blocks(self) -> None:
        result = FootnoteResolver.resolve([])
        assert result == []

    @pytest.mark.unit
    def test_no_footnote_blocks(self) -> None:
        blocks = [
            StructuredBlock(block_type="text", content="正文内容①", page_number=1),
        ]
        result = FootnoteResolver.resolve(blocks)
        assert result[0].image_refs is None

    @pytest.mark.unit
    def test_circled_number_footnote_matched(self) -> None:
        blocks = [
            StructuredBlock(
                block_type="text", content="关于此项①详见辅助材料。", page_number=1,
                layout_tag=LayoutTag.BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="① 辅助材料指附件A中的补充说明。",
                page_number=1, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        assert result[0].image_refs is not None
        assert len(result[0].image_refs) == 1
        assert "footnote:1:1" in result[0].image_refs[0]

    @pytest.mark.unit
    def test_superscript_footnote_matched(self) -> None:
        blocks = [
            StructuredBlock(
                block_type="text", content="参见相关研究¹。", page_number=2,
                layout_tag=LayoutTag.BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="¹ Smith, J. (2020). ...",
                page_number=2, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        assert result[0].image_refs is not None
        assert "footnote:2:1" in result[0].image_refs[0]

    @pytest.mark.unit
    def test_bracket_footnote_matched(self) -> None:
        blocks = [
            StructuredBlock(
                block_type="text", content="参考[1]中的定义。", page_number=1,
                layout_tag=LayoutTag.BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="[1] 张三，李四. 数字孪生综述[J]. 2023.",
                page_number=1, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        assert result[0].image_refs is not None
        assert "footnote:1:1" in result[0].image_refs[0]

    @pytest.mark.unit
    def test_footnote_wrong_page_not_matched(self) -> None:
        blocks = [
            StructuredBlock(
                block_type="text", content="见注释①。", page_number=1,
                layout_tag=LayoutTag.BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="① 这是另一页的脚注。",
                page_number=2, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        assert result[0].image_refs is None

    @pytest.mark.unit
    def test_non_text_source_skipped(self) -> None:
        """表格块（block_type='table'，layout_tag='table_body'）应被跳过。"""
        blocks = [
            StructuredBlock(
                block_type="table", content="① 表格内标记",
                page_number=1, layout_tag=LayoutTag.TABLE_BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="① 脚注内容",
                page_number=1, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        # 表格块不应被匹配（block_type != "text" 且 layout_tag != BODY）
        assert result[0].image_refs is None

    @pytest.mark.unit
    def test_multiple_footnotes_same_page(self) -> None:
        blocks = [
            StructuredBlock(
                block_type="text", content="第一个观点①，第二个观点②。",
                page_number=1, layout_tag=LayoutTag.BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="① 第一个注释。",
                page_number=1, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
            StructuredBlock(
                block_type="text", content="② 第二个注释。",
                page_number=1, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        refs = result[0].image_refs or []
        assert len(refs) == 2

    @pytest.mark.unit
    def test_asterisk_footnote_matched(self) -> None:
        """* 作为脚注标记的前后不能是单词字符。在句末空格后的 * 可匹配。"""
        blocks = [
            StructuredBlock(
                block_type="text", content="This is a claim * that needs evidence.",
                page_number=1, layout_tag=LayoutTag.BODY.value,
            ),
            StructuredBlock(
                block_type="text", content="* Supplementary evidence provided by...",
                page_number=1, layout_tag=LayoutTag.FOOTNOTE.value,
            ),
        ]
        result = FootnoteResolver.resolve(blocks)
        assert result[0].image_refs is not None
        assert "footnote:1:*" in result[0].image_refs[0]
