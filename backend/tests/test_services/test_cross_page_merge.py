"""跨页段落合并 _should_merge_cross_page 单元测试。"""

import pytest

from src.services.chunking_service import ChunkingService


@pytest.mark.unit
def test_empty_inputs() -> None:
    should, sep = ChunkingService._should_merge_cross_page("", "")
    assert should is False
    assert sep == "\n"


@pytest.mark.unit
def test_hyphenated_word_across_pages() -> None:
    """英文断词连字符：prev=-, next 小写开头 → 合并去连字符。"""
    should, sep = ChunkingService._should_merge_cross_page(
        "The information retri-", "val system is critical."
    )
    assert should is True
    assert sep == ""


@pytest.mark.unit
def test_complete_sentence_at_prev_end() -> None:
    """prev 以句号结束 → 不合并。"""
    should, _ = ChunkingService._should_merge_cross_page(
        "这是第一句话。", "这是第二句。"
    )
    assert should is False


@pytest.mark.unit
def test_complete_question_at_prev_end() -> None:
    should, _ = ChunkingService._should_merge_cross_page(
        "这个问题解决了吗？", "答案是肯定的。"
    )
    assert should is False


@pytest.mark.unit
def test_next_is_heading_no_merge() -> None:
    """next 是章节标题 → 不合并。"""
    should, _ = ChunkingService._should_merge_cross_page(
        "这是上一页的最后一段文字。",
        "第三章 系统设计\n",
    )
    assert should is False


@pytest.mark.unit
def test_incomplete_sentence_merged() -> None:
    """prev 未以句末标点结束 → 合并。"""
    should, _ = ChunkingService._should_merge_cross_page(
        "这句话还没有结束", "在下一页继续。"
    )
    assert should is True


@pytest.mark.unit
def test_overlapping_content_deduplicated() -> None:
    """语义重叠 → 去重合并。"""
    should, sep = ChunkingService._should_merge_cross_page(
        "数字孪生系统的核心能力包括实时映射",
        "实时映射和预测仿真两大功能。"
    )
    assert should is True
    assert sep == ""


@pytest.mark.unit
def test_overlap_shorter_than_3_no_dedup() -> None:
    """重叠 < 3 字符 → 不触发去重但默认合并。"""
    should, _ = ChunkingService._should_merge_cross_page(
        "这个句子跨页了",
        "了继续下一句。"
    )
    assert should is True


@pytest.mark.unit
def test_non_consecutive_pages_still_checked() -> None:
    """非连续页号判断由调用方处理，此处仅验证内联函数可处理。"""
    should, _ = ChunkingService._should_merge_cross_page(
        "这是不完整的句子，",
        "它延续到很后面。"
    )
    assert should is True
