"""BM25 FTS5 单元测试。"""

import tempfile
from pathlib import Path

import pytest

from src.services.rag.bm25_fts import BM25FTSRetriever


@pytest.fixture
def fts() -> BM25FTSRetriever:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_fts.db")
        retriever = BM25FTSRetriever(fts_db_path=db_path)
        yield retriever
        retriever.close()


def _make_chunk(chunk_id: str, content: str, doc_id: str = "doc1") -> object:
    from types import SimpleNamespace

    return SimpleNamespace(
        id=chunk_id,
        document_id=doc_id,
        page_start=1,
        chunk_type="text",
        content=content,
    )


@pytest.mark.unit
def test_table_name(fts: BM25FTSRetriever) -> None:
    tbl = fts._table_name("default", "abc123")
    assert tbl.startswith("fts_")
    assert "default" in tbl
    assert "abc123" in tbl


@pytest.mark.unit
def test_build_and_exists(fts: BM25FTSRetriever) -> None:
    assert not fts.table_exists("default", "kb1")
    chunks = [
        _make_chunk("c1", "Python 是一门编程语言"),
        _make_chunk("c2", "Java 广泛用于企业开发"),
        _make_chunk("c3", "Go 语言以并发著称"),
    ]
    fts.build_index("default", "kb1", chunks)
    assert fts.table_exists("default", "kb1")


@pytest.mark.unit
def test_search_returns_results(fts: BM25FTSRetriever) -> None:
    chunks = [
        _make_chunk("c1", "JWT 认证流程详解"),
        _make_chunk("c2", "数据库连接池配置说明"),
        _make_chunk("c3", "JWT Token 刷新机制与过期处理"),
    ]
    fts.build_index("default", "kb2", chunks)
    results = fts.search("default", "kb2", "JWT 认证", top_k=5)
    assert len(results) > 0
    # c1 和 c3 应排在前两位
    chunk_ids = [cid for _, cid, _ in results[:2]]
    assert "c1" in chunk_ids or "c3" in chunk_ids


@pytest.mark.unit
def test_search_nonexistent_kb_returns_empty(fts: BM25FTSRetriever) -> None:
    assert fts.search("default", "nonexistent", "query", top_k=5) == []


@pytest.mark.unit
def test_add_chunks_incremental(fts: BM25FTSRetriever) -> None:
    chunks = [_make_chunk("c1", "初始文档内容")]
    fts.build_index("default", "kb3", chunks)
    results = fts.search("default", "kb3", "新增", top_k=5)
    assert len(results) == 0

    fts.add_chunks("default", "kb3", [_make_chunk("c2", "新增的文档内容")])
    results = fts.search("default", "kb3", "新增", top_k=5)
    assert len(results) > 0


@pytest.mark.unit
def test_delete_chunks(fts: BM25FTSRetriever) -> None:
    chunks = [
        _make_chunk("c1", "Python 编程"),
        _make_chunk("c2", "Java 开发"),
    ]
    fts.build_index("default", "kb4", chunks)
    fts.delete_chunks("default", "kb4", ["c1"])
    results = fts.search("default", "kb4", "Python", top_k=5)
    assert len(results) == 0
    results = fts.search("default", "kb4", "Java", top_k=5)
    assert len(results) > 0


@pytest.mark.unit
def test_drop_index(fts: BM25FTSRetriever) -> None:
    chunks = [_make_chunk("c1", "测试")]
    fts.build_index("default", "kb5", chunks)
    assert fts.table_exists("default", "kb5")
    fts.drop_index("default", "kb5")
    assert not fts.table_exists("default", "kb5")


@pytest.mark.unit
def test_delete_by_document(fts: BM25FTSRetriever) -> None:
    chunks = [
        _make_chunk("c1", "文档A内容", doc_id="doc_a"),
        _make_chunk("c2", "文档B内容", doc_id="doc_b"),
        _make_chunk("c3", "文档A更多", doc_id="doc_a"),
    ]
    fts.build_index("default", "kb6", chunks)
    fts.delete_by_document("default", "kb6", "doc_a")
    results = fts.search("default", "kb6", "文档A", top_k=5)
    assert len(results) == 0
    results = fts.search("default", "kb6", "文档B", top_k=5)
    assert len(results) > 0


@pytest.mark.unit
def test_chinese_tokenize(fts: BM25FTSRetriever) -> None:
    """验证 jieba 中文分词在 FTS5 中正常工作。"""
    chunks = [
        _make_chunk("c1", "数字孪生系统由数据层、模型层和应用层组成"),
        _make_chunk("c2", "微服务架构包含服务发现和负载均衡"),
    ]
    fts.build_index("default", "kb7", chunks)
    results = fts.search("default", "kb7", "数字孪生", top_k=5)
    assert len(results) > 0
    assert results[0][1] == "c1"


@pytest.mark.unit
def test_empty_table_returns_empty(fts: BM25FTSRetriever) -> None:
    chunks: list = []
    fts.build_index("default", "kb8", chunks)
    assert fts.search("default", "kb8", "query", top_k=5) == []
