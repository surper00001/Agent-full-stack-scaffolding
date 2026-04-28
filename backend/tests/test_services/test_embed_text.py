"""Embedding 文本构建单元测试。"""

from types import SimpleNamespace

import pytest

from src.services.knowledge_base_service import KnowledgeBaseService


@pytest.mark.unit
def test_build_embed_text_truncates_long_content() -> None:
    chunk = SimpleNamespace(
        chunk_id="test-chunk",
        section_path=None,
        section_title=None,
        content_summary=None,
        content="中" * 3000,
    )
    result = KnowledgeBaseService._build_embed_text(chunk)
    assert len(result) <= KnowledgeBaseService._EMBED_TEXT_MAX_CHARS


@pytest.mark.unit
def test_truncate_embed_text_at_punctuation() -> None:
    text = "前言。" + "内容。" * 200 + "结尾。"
    truncated = KnowledgeBaseService._truncate_embed_text(text, 500)
    assert len(truncated) <= 500
