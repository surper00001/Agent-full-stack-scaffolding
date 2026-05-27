"""enrich_list_structure 列表嵌套结构分析单元测试。"""

import pytest

from src.services.chunking.data_models import StructuredBlock
from src.services.document_processors.layout import LayoutTag, enrich_list_structure


@pytest.mark.unit
def test_empty_blocks() -> None:
    result = enrich_list_structure([])
    assert result == []


@pytest.mark.unit
def test_no_list_items() -> None:
    blocks = [
        StructuredBlock(block_type="text", content="普通正文段落。", page_number=1),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_level == 0
    assert result[0].list_type == ""


@pytest.mark.unit
def test_ordered_list_detection() -> None:
    blocks = [
        StructuredBlock(
            block_type="text", content="1. 第一步",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="2. 第二步",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 130, 200, 150),
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_type == "ordered"
    assert result[1].list_type == "ordered"


@pytest.mark.unit
def test_unordered_list_detection() -> None:
    blocks = [
        StructuredBlock(
            block_type="text", content="- 项目一",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="• 项目二",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 130, 200, 150),
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_type == "unordered"
    assert result[1].list_type == "unordered"


@pytest.mark.unit
def test_nested_list_level_detection() -> None:
    """一级列表 x0=50，二级缩进 ~24pt → x0=74 → level=1。"""
    blocks = [
        StructuredBlock(
            block_type="text", content="1. 一级项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="- 二级子项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(74, 130, 200, 150),
        ),
        StructuredBlock(
            block_type="text", content="2. 又一个一级项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 160, 200, 180),
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_level == 0
    assert result[1].list_level == 1  # ~24pt 缩进
    assert result[2].list_level == 0


@pytest.mark.unit
def test_deep_nesting_capped_at_4() -> None:
    """极深缩进应被限制在 level=4。"""
    blocks = [
        StructuredBlock(
            block_type="text", content="1. 顶层",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="- 深度嵌套",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50 + 200, 130, 200, 150),  # 极深缩进
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[1].list_level <= 4


@pytest.mark.unit
def test_no_bbox_defaults_to_zero_indent() -> None:
    blocks = [
        StructuredBlock(
            block_type="text", content="1. 无位置信息",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_level == 0


@pytest.mark.unit
def test_mixed_list_types_in_group() -> None:
    blocks = [
        StructuredBlock(
            block_type="text", content="1. 有序项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="• 无序项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 130, 200, 150),
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_type == "ordered"
    assert result[1].list_type == "unordered"


@pytest.mark.unit
def test_chinese_numbered_list() -> None:
    """`一、` 开头的中文编号列表（`一、 ` 带空格）→ ordered。"""
    blocks = [
        StructuredBlock(
            block_type="text", content="一、 第一项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="二、 第二项",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 130, 200, 150),
        ),
    ]
    result = enrich_list_structure(blocks)
    assert result[0].list_type == "ordered"


@pytest.mark.unit
def test_non_list_blocks_interrupt_group() -> None:
    blocks = [
        StructuredBlock(
            block_type="text", content="1. 列表项A",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 100, 200, 120),
        ),
        StructuredBlock(
            block_type="text", content="这是普通段落，不属于列表。",
            page_number=1, layout_tag=LayoutTag.BODY.value,
        ),
        StructuredBlock(
            block_type="text", content="2. 列表项B（新组）",
            page_number=1, layout_tag=LayoutTag.LIST_ITEM.value,
            bbox=(50, 160, 200, 180),
        ),
    ]
    result = enrich_list_structure(blocks)
    # 第一组
    assert result[0].list_level == 0
    # 中间的非列表项不变
    assert result[1].layout_tag == LayoutTag.BODY.value
    assert result[1].list_type == ""
    # 新组
    assert result[2].list_type == "ordered"
