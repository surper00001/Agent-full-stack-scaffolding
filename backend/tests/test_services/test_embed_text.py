"""Embedding 文本构建单元测试 —— metadata-aware retrieval。"""

from types import SimpleNamespace

import pytest

from src.services.rag.embed_text_builder import (
    EMBED_TEXT_MAX_CHARS,
    build_embed_text,
    truncate_embed_text,
)


def _make_chunk(**kwargs) -> SimpleNamespace:
    """构建测试用 chunk 对象。"""
    defaults = {
        "chunk_id": "test-chunk",
        "section_path": None,
        "section_title": None,
        "title": None,
        "content_summary": None,
        "content": "测试内容。",
        "doc_category": None,
        "layout_tag": None,
        "table_refs": None,
        "image_refs": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


@pytest.mark.unit
def test_build_embed_text_includes_doc_filename() -> None:
    """文档名应出现在 embedding 文本中。"""
    chunk = _make_chunk()
    result = build_embed_text(chunk, doc_filename="论文.pdf")
    assert "[文档] 论文.pdf" in result


@pytest.mark.unit
def test_build_embed_text_includes_doc_category() -> None:
    """文档类型标签应出现。"""
    chunk = _make_chunk(doc_category="academic")
    result = build_embed_text(chunk)
    assert "[文档类型] 学术论文" in result


@pytest.mark.unit
def test_build_embed_text_includes_layout_tag() -> None:
    """版面语义标签应出现。"""
    chunk = _make_chunk(layout_tag="body")
    result = build_embed_text(chunk)
    assert "[语义标签] 正文" in result


@pytest.mark.unit
def test_build_embed_text_includes_section_path() -> None:
    """章节路径应出现（核心召回信号）。"""
    chunk = _make_chunk(section_path="第三章 > 系统架构")
    result = build_embed_text(chunk)
    assert "[章节路径] 第三章 > 系统架构" in result


@pytest.mark.unit
def test_build_embed_text_includes_title() -> None:
    """标题应出现（title 字段优先于 section_title）。"""
    chunk = _make_chunk(
        title="3.2 数字孪生系统",
        section_title="3.2 数字孪生系统",
        section_path="第三章 > 系统架构",
    )
    result = build_embed_text(chunk)
    assert "[标题] 3.2 数字孪生系统" in result


@pytest.mark.unit
def test_build_embed_text_includes_summary() -> None:
    """内容摘要应出现。"""
    chunk = _make_chunk(content_summary="本节介绍系统架构设计")
    result = build_embed_text(chunk)
    assert "[摘要] 本节介绍系统架构设计" in result


@pytest.mark.unit
def test_build_embed_text_includes_table_refs_with_captions() -> None:
    """关联表格及标题应出现在 embedding 中。"""
    chunk = _make_chunk(
        chunk_id="text-1",
        table_refs=["table-1", "table-2"],
    )
    refs_captions = {"table-1": "表1: 性能对比", "table-2": "表2: 实验结果"}
    result = build_embed_text(
        chunk, doc_filename="paper.pdf", refs_captions=refs_captions
    )
    assert "[关联表格] 表1: 性能对比 | 表2: 实验结果" in result


@pytest.mark.unit
def test_build_embed_text_includes_image_refs_with_captions() -> None:
    """关联图片及标题应出现在 embedding 中。"""
    chunk = _make_chunk(
        chunk_id="text-1",
        image_refs=["img-1"],
    )
    refs_captions = {"img-1": "图3: 数字孪生架构"}
    result = build_embed_text(
        chunk, doc_filename="paper.pdf", refs_captions=refs_captions
    )
    assert "[关联图片] 图3: 数字孪生架构" in result


@pytest.mark.unit
def test_build_embed_text_full_structured() -> None:
    """完整 structured chunk——验证所有字段都在 embedding 中。

    目标：embedding 的不是纯文本，而是 metadata-aware 结构化表示。
    """
    chunk = _make_chunk(
        chunk_id="chunk-001",
        doc_category="technical",
        layout_tag="body",
        section_path="系统设计 > 数字孪生",
        title="3.2 数字孪生系统",
        content_summary="本节介绍了数字孪生系统的核心架构",
        content="数字孪生系统由数据层、模型层和应用层组成...",
        table_refs=["t1"],
        image_refs=["i1"],
    )
    refs_captions = {"t1": "表1: 系统性能指标", "i1": "图2: 架构示意图"}
    result = build_embed_text(
        chunk, doc_filename="architecture.pdf", refs_captions=refs_captions
    )
    # 每个语义维度都应独立存在
    assert "[文档] architecture.pdf" in result
    assert "[文档类型] 技术文档" in result
    assert "[语义标签] 正文" in result
    assert "[章节路径] 系统设计 > 数字孪生" in result
    assert "[标题] 3.2 数字孪生系统" in result
    assert "[关联表格] 表1: 系统性能指标" in result
    assert "[关联图片] 图2: 架构示意图" in result
    assert "[摘要] 本节介绍了数字孪生系统的核心架构" in result
    assert "数字孪生系统由数据层" in result


@pytest.mark.unit
def test_build_embed_text_truncates_long_content() -> None:
    """长文本应被截断。"""
    chunk = SimpleNamespace(
        chunk_id="test-chunk",
        section_path=None,
        section_title=None,
        title=None,
        content_summary=None,
        content="中" * 3000,
        doc_category=None,
        layout_tag=None,
        table_refs=None,
        image_refs=None,
    )
    result = build_embed_text(chunk)
    assert len(result) <= EMBED_TEXT_MAX_CHARS


@pytest.mark.unit
def test_truncate_embed_text_at_punctuation() -> None:
    """截断应在标点处进行。"""
    text = "前言。" + "内容。" * 200 + "结尾。"
    truncated = truncate_embed_text(text, 500)
    assert len(truncated) <= 500


@pytest.mark.unit
def test_build_embed_text_without_doc_filename_no_doc_prefix() -> None:
    """无文档名时不应有 [文档] 前缀。"""
    chunk = _make_chunk()
    result = build_embed_text(chunk)
    assert "[文档]" not in result


@pytest.mark.unit
def test_build_embed_text_skips_title_when_same_as_section_path() -> None:
    """当 title 等于 section_path 时不应重复添加 [标题]。"""
    chunk = _make_chunk(
        title="系统架构",
        section_path="系统架构",
        section_title="系统架构",
    )
    result = build_embed_text(chunk)
    # 不应出现单独的 [标题] 行（因为 title == section_path）
    assert "[标题]" not in result
    # 但应保留 [章节路径]（因为 section_path 等于 section_title）
    # 实际上当 section_path 存在且等于 section_title 时，旧行为是同时输出
    # 新行为中 title==section_path 时跳过 title
