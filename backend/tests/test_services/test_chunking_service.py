"""ChunkingService 中文分块单元测试。"""

import pytest

from src.services.chunking_service import ChunkingService, StructuredBlock
from src.services.document_analyzer import DocCategory, DocStructure


def _make_zh_structure() -> DocStructure:
    return DocStructure(
        category=DocCategory.GENERAL,
        confidence=0.8,
        total_pages=2,
        headings=[],
        text_ratio=0.9,
        detected_lang="zh",
        recommended_chunk_size=300,
        recommended_chunk_overlap=30,
    )


@pytest.mark.unit
def test_kb_chunk_size_not_overridden_by_doc_structure() -> None:
    chunker = ChunkingService(
        child_chunk_size=768,
        child_chunk_overlap=128,
        doc_structure=_make_zh_structure(),
    )
    assert chunker.child_chunk_size == 768
    assert chunker.child_chunk_overlap == 128


@pytest.mark.unit
def test_zh_structure_clamps_chunk_size() -> None:
    chunker = ChunkingService(
        child_chunk_size=2000,
        child_chunk_overlap=50,
        doc_structure=_make_zh_structure(),
    )
    assert chunker.child_chunk_size == 1200


@pytest.mark.unit
def test_chapter_regex_split() -> None:
    chunker = ChunkingService(doc_structure=_make_zh_structure())
    text = (
        "这是较长的前言段落，用于触发分块逻辑。"
        "\n第一章 系统概述\n"
        + "本章介绍系统的核心能力与边界。" * 5
        + "\n第二章 实现细节\n"
        + "更多实现层面的说明文字。" * 5
    )
    parts = chunker._split_text(text, 80, 10)
    assert len(parts) >= 2
    assert any("第一章" in p for p in parts)
    assert any("第二章" in p for p in parts)


@pytest.mark.unit
def test_force_split_respects_sentence_boundary() -> None:
    chunker = ChunkingService()
    long_text = "这是第一句。" + "中间内容很长。" * 30 + "最后一句。"
    parts = chunker._force_split(long_text, chunk_size=80, chunk_overlap=10)
    assert len(parts) >= 2
    for part in parts:
        assert part.strip()


@pytest.mark.unit
def test_merge_text_stream_cross_page_incomplete_sentence() -> None:
    chunker = ChunkingService()
    blocks = [
        StructuredBlock(block_type="text", content="这句话没有结束，继续", page_number=1),
        StructuredBlock(block_type="text", content="在下一页完成。", page_number=2),
    ]
    merged = chunker._merge_text_stream(blocks)
    assert len(merged) == 1
    assert "继续" in merged[0].content
    assert "下一页" in merged[0].content


@pytest.mark.unit
def test_semantic_separators_exclude_comma() -> None:
    assert "，" not in ChunkingService._SEPARATORS_SEMANTIC
    assert "、" not in ChunkingService._SEPARATORS_SEMANTIC


@pytest.mark.unit
def test_char_count_consistency_in_merge_small() -> None:
    chunker = ChunkingService()
    short = "短"
    assert chunker._char_count(short) < 50
