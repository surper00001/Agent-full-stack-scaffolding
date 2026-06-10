"""
混合检索服务——向量 + BM25 融合。

对专有名词、编号类 query 效果显著；通过 RRF 合并候选后再交给 reranker。
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document
from loguru import logger

if TYPE_CHECKING:
    from src.services.rag.bm25_fts import BM25FTSRetriever
    from src.vectorstore.base import BaseVectorStore


class HybridSearchService:
    """BM25 + 向量检索的 RRF 融合。

    支持两种 BM25 后端：
    - memory: 全量加载到内存（rank_bm25），适合小 KB
    - sqlite_fts5: SQLite FTS5 磁盘索引，启动零内存
    """

    def __init__(self, vector_store: BaseVectorStore) -> None:
        self._vector_store = vector_store
        self._bm25_cache: dict[str, Any] = {}
        self._fts_retriever: BM25FTSRetriever | None = None  # lazy init for sqlite_fts5 backend

    async def search(
        self,
        kb_id: str,
        tenant_id: str,
        query: str,
        query_vector: list[float],
        collection_name: str,
        top_k: int,
        vector_filter: dict[str, Any] | None,
        chunk_repo: Any,
    ) -> list[Document]:
        """执行混合检索并返回融合后的 Document 列表。"""
        vector_results = await self._vector_store.similarity_search_by_vector(
            query_embedding=query_vector,
            collection_name=collection_name,
            tenant_id=tenant_id,
            top_k=top_k,
            filter=vector_filter,
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
        """BM25 关键词检索，返回 (chunk_id, Document) 列表。

        后端选择: 根据 kb_bm25_backend 配置自动切换 memory / sqlite_fts5。
        """
        from src.core.config import get_settings

        settings = get_settings()
        if settings.kb_bm25_backend == "sqlite_fts5":
            return await self._bm25_search_fts5(kb_id, tenant_id, query, top_k, chunk_repo)
        return await self._bm25_search_memory(kb_id, tenant_id, query, top_k, chunk_repo)

    async def _bm25_search_fts5(
        self,
        kb_id: str,
        tenant_id: str,
        query: str,
        top_k: int,
        chunk_repo: Any,
    ) -> list[tuple[str, Document]]:
        """SQLite FTS5 路径 —— 零内存 BM25 检索。"""
        from src.services.rag.bm25_fts import get_bm25_fts_retriever

        if self._fts_retriever is None:
            self._fts_retriever = get_bm25_fts_retriever()

        # 如果 FTS5 表不存在，后台构建 + 本次降级（跳过 BM25）
        if not self._fts_retriever.table_exists(tenant_id, kb_id):
            logger.info(
                f"FTS5 索引不存在，触发后台构建 + 本次降级纯向量: kb={kb_id}"
            )
            # 触发后台构建（不等待），避免阻塞首次搜索
            asyncio = __import__("asyncio")
            asyncio.ensure_future(
                self._build_fts5_background(kb_id, tenant_id, chunk_repo)
            )
            return []  # 降级：本次跳过 BM25

        fts_results = self._fts_retriever.search(tenant_id, kb_id, query, top_k)

        # 批量加载 chunk 元数据
        chunk_ids = [cid for _, cid, _ in fts_results]
        if not chunk_ids:
            return []

        from src.models.domain.knowledge_base import KBChunk

        chunk_map = await self._load_chunks_by_ids(chunk_ids, chunk_repo, KBChunk)

        results: list[tuple[str, Document]] = []
        for bm25_score, chunk_id, fts_meta in fts_results:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            meta = chunk.metadata_ or {}
            doc = Document(
                page_content=chunk.content,
                metadata={
                    "chunk_id": chunk.vector_id or chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "page_start": chunk.page_start or fts_meta.get("page_start", 1),
                    "page_end": chunk.page_end or 1,
                    "chunk_type": chunk.chunk_type or "text",
                    "parent_chunk_id": chunk.parent_chunk_id,
                    "section_title": meta.get("section_title", ""),
                    "section_path": meta.get("section_path", ""),
                    "content_summary": meta.get("content_summary", ""),
                    "bm25_score": float(bm25_score),
                    "score": float(bm25_score),
                },
            )
            results.append((chunk.vector_id or chunk.id, doc))
        return results

    async def _bm25_search_memory(
        self,
        kb_id: str,
        tenant_id: str,
        query: str,
        top_k: int,
        chunk_repo: Any,
    ) -> list[tuple[str, Document]]:
        """内存 rank_bm25 路径（旧实现，保留兼容）。"""
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

    async def _build_fts5_background(
        self,
        kb_id: str,
        tenant_id: str,
        chunk_repo: Any,
    ) -> None:
        """后台异步构建 FTS5 索引，避免阻塞首次搜索。"""
        import asyncio as _asyncio

        if self._fts_retriever is None:
            logger.warning(f"FTS5 检索器未初始化，跳过后台构建: kb={kb_id}")
            return

        try:
            chunks = await chunk_repo.list_all(
                tenant_id=tenant_id, knowledge_base_id=kb_id, limit=100000
            )
            if chunks:
                # run_in_executor 将 CPU 密集的构建操作放到线程池
                loop = _asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    self._fts_retriever.build_index,
                    tenant_id, kb_id, chunks,
                )
                logger.info(
                    f"FTS5 后台构建完成: kb={kb_id}, chunks={len(chunks)}"
                )
        except Exception as e:
            logger.warning(f"FTS5 后台构建失败: kb={kb_id}, err={e}")

    def invalidate_cache(self, kb_id: str, tenant_id: str) -> None:
        """文档变更后清除 BM25 缓存。"""
        self._bm25_cache.pop(f"{tenant_id}:{kb_id}", None)
        # FTS5 路径：删除旧表，下次搜索时自动重建
        if self._fts_retriever is not None:
            with contextlib.suppress(Exception):
                self._fts_retriever.drop_index(tenant_id, kb_id)

    @staticmethod
    async def _load_chunks_by_ids(
        chunk_ids: list[str],
        chunk_repo: Any,
        chunk_model: Any,
    ) -> dict[str, Any]:
        """批量加载 chunk 对象，返回 {chunk_id: chunk} 映射。"""
        from sqlalchemy import select

        if not chunk_ids:
            return {}
        stmt = select(chunk_model).where(chunk_model.id.in_(chunk_ids))
        result = await chunk_repo._session.execute(stmt)
        return {c.id: c for c in result.scalars().all()}
