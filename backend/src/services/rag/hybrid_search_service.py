"""
混合检索服务——向量 + BM25 融合。

对专有名词、编号类 query 效果显著；通过 RRF 合并候选后再交给 reranker。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from loguru import logger

if TYPE_CHECKING:
    from src.vectorstore.chroma_store import ChromaVectorStore


class HybridSearchService:
    """BM25 + 向量检索的 RRF 融合。"""

    def __init__(self, vector_store: ChromaVectorStore) -> None:
        self._vector_store = vector_store
        self._bm25_cache: dict[str, Any] = {}

    async def search(
        self,
        kb_id: str,
        tenant_id: str,
        query: str,
        query_vector: list[float],
        collection_name: str,
        top_k: int,
        chroma_filter: dict[str, Any] | None,
        chunk_repo: Any,
    ) -> list[Document]:
        """执行混合检索并返回融合后的 Document 列表。"""
        vector_results = await self._vector_store.similarity_search_by_vector(
            query_embedding=query_vector,
            collection_name=collection_name,
            tenant_id=tenant_id,
            top_k=top_k,
            filter=chroma_filter,
        )

        try:
            bm25_results = await self._bm25_search(
                kb_id, tenant_id, query, top_k, chunk_repo
            )
            return self._rrf_merge(vector_results, bm25_results, top_k)
        except Exception as e:
            logger.warning(f"BM25 检索失败，降级为纯向量: {e}")
            return vector_results

    async def _bm25_search(
        self,
        kb_id: str,
        tenant_id: str,
        query: str,
        top_k: int,
        chunk_repo: Any,
    ) -> list[tuple[str, Document]]:
        """BM25 关键词检索，返回 (chunk_id, Document) 列表。"""
        import jieba
        from rank_bm25 import BM25Okapi

        cache_key = f"{tenant_id}:{kb_id}"
        if cache_key not in self._bm25_cache:
            chunks = await chunk_repo.list_all(
                tenant_id=tenant_id, knowledge_base_id=kb_id, limit=100000
            )
            corpus = [c.content for c in chunks]
            tokenized = [list(jieba.cut_for_search(doc)) for doc in corpus]
            bm25 = BM25Okapi(tokenized)
            self._bm25_cache[cache_key] = (bm25, chunks)

        bm25, chunks = self._bm25_cache[cache_key]
        query_tokens = list(jieba.cut_for_search(query))
        scores = bm25.get_scores(query_tokens)

        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)
        results: list[tuple[str, Document]] = []
        for idx, score in indexed[:top_k]:
            if score <= 0:
                continue
            chunk = chunks[idx]
            meta = chunk.metadata_ or {}
            doc = Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": chunk.vector_id or chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start,
                    "page_end": chunk.page_end,
                    "chunk_type": chunk.chunk_type,
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "section_title": meta.get("section_title", ""),
                    "section_path": meta.get("section_path", ""),
                    "content_summary": meta.get("content_summary", ""),
                    "bm25_score": float(score),
                    "score": float(score),
                },
            )
            results.append((chunk.vector_id or chunk.id, doc))
        return results

    @staticmethod
    def _rrf_merge(
        vector_results: list[Document],
        bm25_results: list[tuple[str, Document]],
        top_k: int,
        k: int = 60,
    ) -> list[Document]:
        """Reciprocal Rank Fusion 合并两路检索结果。"""
        scores: dict[str, float] = {}
        doc_map: dict[str, Document] = {}

        for rank, doc in enumerate(vector_results):
            cid = doc.metadata.get("chunk_id", str(rank))
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            doc_map[cid] = doc

        for rank, (cid, doc) in enumerate(bm25_results):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in doc_map:
                doc_map[cid] = doc

        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)
        merged: list[Document] = []
        for cid in sorted_ids[:top_k]:
            doc = doc_map[cid]
            doc.metadata["score"] = scores[cid]
            merged.append(doc)
        return merged

    def invalidate_cache(self, kb_id: str, tenant_id: str) -> None:
        """文档变更后清除 BM25 缓存。"""
        self._bm25_cache.pop(f"{tenant_id}:{kb_id}", None)
