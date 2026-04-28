"""Embedding 策略单元测试。"""

import pytest

from src.services.rag.embedding_strategy import (
    BGEStrategy,
    Qwen3Strategy,
    get_embedding_strategy,
)


@pytest.mark.unit
def test_bge_query_has_prefix() -> None:
    strategy = BGEStrategy("BAAI/bge-large-zh-v1.5")
    q = strategy.format_query("测试查询")
    assert "检索" in q
    assert "测试查询" in q
    assert strategy.format_document("文档内容") == "文档内容"


@pytest.mark.unit
def test_qwen3_encode_kwargs() -> None:
    strategy = Qwen3Strategy("Qwen/Qwen3-Embedding-0.6B")
    assert strategy.encode_kwargs_for_query() == {"prompt_name": "query"}
    assert strategy.encode_kwargs_for_document() == {"prompt_name": "document"}


@pytest.mark.unit
def test_factory_selects_qwen3() -> None:
    strategy = get_embedding_strategy("Qwen/Qwen3-Embedding-0.6B")
    assert isinstance(strategy, Qwen3Strategy)


@pytest.mark.unit
def test_factory_selects_bge() -> None:
    strategy = get_embedding_strategy("BAAI/bge-large-zh-v1.5")
    assert isinstance(strategy, BGEStrategy)
