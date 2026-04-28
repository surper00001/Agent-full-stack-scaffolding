"""RAG context_builder 单元测试。"""

import json

import pytest

from src.services.rag.context_builder import (
    CitationItem,
    build_system_rag_prompt,
    format_context_text,
    merge_citations,
    parse_tool_result_citations,
)


@pytest.mark.unit
def test_format_context_text_includes_source_and_score() -> None:
    citations = [
        CitationItem(
            chunk_id="c1",
            content="JWT 认证流程说明",
            source="api.pdf",
            page=3,
            score=0.87,
            section_title="认证",
        )
    ]
    text = format_context_text(citations)
    assert "api.pdf" in text
    assert "JWT 认证流程说明" in text
    assert "87%" in text
    assert "认证" in text


@pytest.mark.unit
def test_build_system_rag_prompt_empty_when_no_context() -> None:
    assert build_system_rag_prompt("测试库", "") == ""
    assert build_system_rag_prompt("测试库", "   ") == ""


@pytest.mark.unit
def test_build_system_rag_prompt_contains_kb_name() -> None:
    prompt = build_system_rag_prompt("产品文档", "一些内容")
    assert "产品文档" in prompt
    assert "知识库检索结果" in prompt


@pytest.mark.unit
def test_parse_tool_result_citations() -> None:
    payload = json.dumps({
        "results": [
            {
                "chunk_id": "abc",
                "content": "hello",
                "source": "doc.pdf",
                "page": 2,
                "score": 0.5,
            }
        ]
    })
    cites = parse_tool_result_citations(payload)
    assert len(cites) == 1
    assert cites[0].chunk_id == "abc"
    assert cites[0].source == "doc.pdf"


@pytest.mark.unit
def test_merge_citations_dedup_by_chunk_id() -> None:
    a = CitationItem("id1", "v1", "s", 1, 0.3)
    b = CitationItem("id1", "v2", "s", 1, 0.9)
    c = CitationItem("id2", "v3", "s", 1, 0.5)
    merged = merge_citations([a], [b, c])
    assert len(merged) == 2
    by_id = {m.chunk_id: m for m in merged}
    assert by_id["id1"].score == 0.9
    assert by_id["id1"].content == "v2"
