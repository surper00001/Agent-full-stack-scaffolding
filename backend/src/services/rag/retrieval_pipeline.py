"""
RAG 检索编排管道。

职责：embed → 向量检索 → (可选) 混合检索 → rerank → 去重/MMR → 上下文扩展。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from langchain_core.documents import Document

from src.core.config import get_settings
from src.core.exceptions import ValidationError, VectorStoreError
from src.services.kb_utils import build_image_url, build_rerank_text
from src.services.rag.embedding_strategy import get_embedding_strategy

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.models.domain.knowledge_base import KnowledgeBase
    from src.services.rag.hybrid_search_service import HybridSearchService
    from src.vectorstore.base import BaseVectorStore


class RetrievalPipeline:
    """知识库检索管道——编排向量检索与精排。"""

    def __init__(
        self,
        session: AsyncSession,
        vector_store: BaseVectorStore,
        hybrid_search: HybridSearchService | None = None,
    ) -> None:
        self._session = session
        self._vector_store = vector_store
        self._hybrid_search = hybrid_search
        self._settings = get_settings()

    async def search(
        self,
        kb: KnowledgeBase,
        query: str,
        tenant_id: str,
        collection_name: str,
        top_k: int = 5,
        rerank: bool = True,
        filters: dict[str, Any] | None = None,
        doc_repo: Any = None,
        signal: Any = None,  # AbortSignal | None
    ) -> dict[str, Any]:
        """执行完整检索流程（含全链路日志 + Langfuse Trace）。

        Args:
            signal: 可选的 AbortSignal，用于中途取消检索。
        """
        t_total_start = time.perf_counter()
        _timings: dict[str, float] = {}

        from src.monitoring.tracer import get_monitor
        _mon = get_monitor()

        # 检查取消信号
        if signal is not None:
            signal.throw_if_aborted()

        # ═══ Step 1: Query 改写 + Embedding ═══
        logger.info(f"[检索 Step1] query='{query[:120]}' top_k={top_k} rerank={rerank}")

        embedding_model = kb.embedding_model or self._settings.kb_embedding_model
        reranker_model = kb.reranker_model or self._settings.kb_reranker_model
        strategy = get_embedding_strategy(embedding_model)

        # ── Query 改写（HyDE）──
        # 短 query 语义密度低，生成假设文档片段后再做 embedding 检索
        # 原始 query 保留给 reranker（精排需要精确语义匹配）
        search_query = query  # 用于向量/BM25 检索的 query
        t_rewrite_start = time.perf_counter()
        with _mon.trace("rag.step1.rewrite", {"query_len": len(query)}):
            try:
                from src.services.rag.query_rewriter import rewrite_query

                search_query = await rewrite_query(query)
                _timings["rewrite"] = (time.perf_counter() - t_rewrite_start) * 1000
            except Exception as e:
                logger.debug(f"Query 改写跳过: {e}")
                _timings["rewrite"] = 0.0

        await self._validate_index_model(collection_name, tenant_id, embedding_model)

        search_k = min(top_k * 5 if rerank else top_k, 50)
        vector_filter = self._build_vector_filter(filters)

        from src.services.embedding_service import get_embedding_service
        from src.services.reranker_service import get_reranker_service

        embedding_svc = get_embedding_service(embedding_model)
        t_embed_start = time.perf_counter()
        query_vector = await embedding_svc.embed_query(search_query, strategy=strategy)
        _timings["embed"] = (time.perf_counter() - t_embed_start) * 1000

        if signal is not None:
            signal.throw_if_aborted()

        # ═══ Step 2: Top-K Retrieval ═══
        hybrid_used = (
            self._hybrid_search is not None
            and self._settings.kb_hybrid_search_enabled
        )
        t_retrieval_start = time.perf_counter()
        with _mon.trace("rag.step2.retrieve", {"mode": "hybrid" if hybrid_used else "vector", "top_k": search_k}):
            try:
                if hybrid_used:
                    from src.db.repository import BaseRepository
                    from src.models.domain.knowledge_base import KBChunk

                    chunk_repo = BaseRepository[KBChunk](KBChunk, self._session)
                    hs = self._hybrid_search
                    assert hs is not None
                    results = await hs.search(
                        kb_id=kb.id,
                        tenant_id=tenant_id,
                        query=search_query,  # 用改写后的 query 提升 BM25 召回
                        query_vector=query_vector,
                        collection_name=collection_name,
                        top_k=search_k,
                        vector_filter=vector_filter,
                        chunk_repo=chunk_repo,
                    )
                else:
                    results = await self._vector_store.similarity_search_by_vector(
                        query_embedding=query_vector,
                        collection_name=collection_name,
                        tenant_id=tenant_id,
                        top_k=search_k,
                        filter=vector_filter,
                    )
            except VectorStoreError:
                raise
            except Exception as e:
                logger.error(f"向量检索失败: {e}")
                raise VectorStoreError(f"向量检索失败: {e}") from e

        total_found = len(results)
        _timings["retrieval"] = (time.perf_counter() - t_retrieval_start) * 1000
        logger.info(
            f"[检索 Step2] 粗排完成: total_found={total_found} "
            f"mode={'hybrid' if hybrid_used else 'vector'}"
        )
        if results:
            self._log_top_results(results[:8], "Step2 粗排样本")

        if not results:
            _timings["total"] = (time.perf_counter() - t_total_start) * 1000
            self._log_metrics(query[:60], top_k, total_found, False, _timings)
            return {
                "query": query, "results": [], "total_found": 0,
                "reranked": False, "low_confidence": False,
            }

        if signal is not None:
            signal.throw_if_aborted()

        # ═══ Step 3: Rerank ═══
        t_rerank_start = time.perf_counter()
        with _mon.trace("rag.step3.rerank", {"candidates": len(results), "model": reranker_model}):
            reranker = get_reranker_service(reranker_model)
            if rerank and len(results) > 0:
                candidate_texts = [
                    build_rerank_text(doc.metadata or {}, doc.page_content) for doc in results
                ]
                logger.info(
                    f"[检索 Step3] 送入重排序: candidates={len(candidate_texts)} "
                    f"model={reranker_model}"
                )
                reranked = await reranker.rerank(
                    query, candidate_texts, top_k=search_k, model_name=reranker_model
                )
                sorted_results = [(results[idx], score) for idx, score in reranked]
            else:
                sorted_results = [
                    (doc, self._doc_score(doc)) for doc in results[:search_k]
                ]
        _timings["rerank"] = (time.perf_counter() - t_rerank_start) * 1000

        # ═══ Step 4: Dedup + MMR ═══
        t_dedup_start = time.perf_counter()
        with _mon.trace("rag.step4.dedup", {"pre_count": len(sorted_results)}):
            pre_dedup_count = len(sorted_results)
            # 记录去重前最高分，用于低置信度检测
            pre_dedup_max_score = sorted_results[0][1] if sorted_results else 0.0
            sorted_results = self._deduplicate_results(sorted_results, top_k)
        _timings["dedup"] = (time.perf_counter() - t_dedup_start) * 1000

        # 低置信度检测：有候选但全被分数阈值过滤
        low_confidence = (
            pre_dedup_count > 0 and len(sorted_results) == 0
        )
        logger.info(
            f"[检索 Step4] 去重/MMR: {pre_dedup_count} → {len(sorted_results)} "
            f"(target top_k={top_k})"
            + (f" ⚠ 低置信度(最高分={pre_dedup_max_score:.3f})" if low_confidence else "")
        )
        if sorted_results:
            self._log_top_results(sorted_results, "Step4 精排结果")

        # 低置信度时仍返回提示信息，帮助 Agent 区分"无内容"与"质量低"
        if low_confidence and not sorted_results:
            _timings["context"] = 0.0
            _timings["total"] = (time.perf_counter() - t_total_start) * 1000
            self._log_metrics(query[:60], top_k, total_found, rerank, _timings)
            return {
                "query": query,
                "results": [],
                "total_found": total_found,
                "reranked": rerank,
                "low_confidence": True,
                "suggestion": (
                    "知识库中未找到高质量匹配内容。"
                    f"最佳匹配得分 {pre_dedup_max_score:.3f} 低于阈值。"
                    "建议尝试不同的搜索词或更具体的查询。"
                ),
            }

        t_context_start = time.perf_counter()
        with _mon.trace("rag.context", {"result_count": len(sorted_results)}):
            # ── 批量预加载上下文（避免 N+1 DB 查询）──
            # 原逐个循环：每结果触发 1×doc + 2×adjacent + 1×parent = 4 次 DB
            # 优化后：批量查询 → 3-4 次 DB 覆盖全部结果
            doc_info_map: dict[str, tuple[str, str, str]] = {}
            adjacent_map: dict[tuple[str, int], tuple[str | None, str | None]] = {}
            parent_map: dict[str, str] = {}

            if sorted_results:
                metas = [(doc.metadata or {}) for doc, _ in sorted_results]

                # 批量加载文档信息
                unique_doc_ids = list({m.get("document_id", "") for m in metas if m.get("document_id")})
                if doc_repo is not None and unique_doc_ids:
                    doc_info_map = await self._batch_load_doc_info(
                        unique_doc_ids, tenant_id, doc_repo
                    )

                # 批量加载相邻 chunk
                adj_pairs: list[tuple[str, int]] = []
                for m in metas:
                    did = m.get("document_id", "")
                    ci = m.get("chunk_index", 0)
                    if did:
                        adj_pairs.append((did, ci))
                if adj_pairs:
                    adjacent_map = await self._batch_load_adjacent_chunks(
                        adj_pairs, tenant_id
                    )

                # 批量加载 parent chunk 上下文
                unique_parent_ids = [
                    pid for m in metas
                    if (pid := m.get("parent_chunk_id"))
                ]
                if unique_parent_ids:
                    parent_map = await self._batch_load_parent_contexts(
                        unique_parent_ids, tenant_id
                    )

            _timings["context"] = (time.perf_counter() - t_context_start) * 1000

            # ── 组装最终结果 ──
            search_results: list[dict[str, Any]] = []

            for doc, score in sorted_results:
                meta = doc.metadata or {}
                chunk_id = meta.get("chunk_id", "")
                doc_id = meta.get("document_id", "")
                chunk_index = meta.get("chunk_index", 0)
                parent_id = meta.get("parent_chunk_id")

                # 从批量预加载结果中获取
                doc_filename, doc_file_type, stored_path = doc_info_map.get(
                    doc_id, ("未知文件", "unknown", "")
                )

                image_path = meta.get("image_path") or ""
                image_url = build_image_url(kb.id, doc_id, image_path, stored_path)

                ctx_before, ctx_after = adjacent_map.get(
                    (doc_id, chunk_index), (None, None)
                )
                parent_context = parent_map.get(parent_id) if parent_id else doc.page_content
                if not parent_context:
                    parent_context = doc.page_content

                search_results.append({
                    "chunk_id": chunk_id,
                    "document_id": doc_id,
                    "content": doc.page_content,
                    "expanded_content": parent_context if parent_context != doc.page_content else None,
                    "chunk_type": meta.get("chunk_type", "text"),
                    "page_start": meta.get("page_start", 1),
                    "page_end": meta.get("page_end", 1),
                    "score": round(float(score), 4),
                    "document_filename": doc_filename,
                    "document_file_type": doc_file_type,
                    "metadata_": {
                        "table_html": meta.get("table_html", ""),
                        "image_path": image_path,
                        "image_url": image_url or "",
                        "is_table_image": meta.get("chunk_type") == "table" and bool(image_path),
                        "ocr_status": meta.get("ocr_status", ""),
                        "ocr_error": meta.get("ocr_error", ""),
                        "image_caption": meta.get("image_caption", ""),
                        "image_description": meta.get("image_description", ""),
                        "table_caption": meta.get("table_caption", ""),
                        "image_width": meta.get("image_width"),
                        "image_height": meta.get("image_height"),
                        "section_title": meta.get("section_title", ""),
                        "section_path": meta.get("section_path", ""),
                        "title": meta.get("title") or meta.get("section_title", ""),
                        "content_summary": meta.get("content_summary", ""),
                        "doc_category": meta.get("doc_category", ""),
                        "layout_tag": meta.get("layout_tag", ""),
                        "table_refs": meta.get("table_refs") or [],
                        "image_refs": meta.get("image_refs") or [],
                        "document_filename": meta.get("document_filename") or doc_filename,
                        "bbox": meta.get("bbox"),
                        "parent_context": parent_context if parent_context != doc.page_content else "",
                    },
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                })

        # ═══ Step 5: Final Context ═══
        final_sources = [r.get("document_filename", "?") for r in search_results]
        final_pages = [r.get("page_start", 0) for r in search_results]
        final_scores = [r.get("score", 0) for r in search_results]
        final_tags = [
            (r.get("metadata_") or {}).get("layout_tag", "") or r.get("chunk_type", "")
            for r in search_results
        ]
        logger.info(
            f"[检索 Step5] 最终上下文: count={len(search_results)} "
            f"scores={[f'{s:.3f}' for s in final_scores]} "
            f"types={final_tags} "
            f"sources={list(zip(final_sources, final_pages, strict=False))}"
        )

        _timings["total"] = (time.perf_counter() - t_total_start) * 1000
        self._log_metrics(query[:60], top_k, total_found, rerank, _timings)

        return {
            "query": query,
            "results": search_results,
            "total_found": total_found,
            "reranked": rerank,
            "low_confidence": low_confidence,
        }

    @staticmethod
    def _log_top_results(
        items: list[tuple[Any, float]] | list[Any],
        label: str,
    ) -> None:
        """打印前几条检索结果的关键信息。"""
        top = items[:5]
        for i, item in enumerate(top):
            if isinstance(item, tuple):
                doc, score = item
            else:
                doc, score = item, 0.0
            meta = doc.metadata or {}
            logger.info(
                f"  [{label}] #{i + 1} score={score:.4f} "
                f"src={meta.get('document_filename', '?') or meta.get('source', '?')} "
                f"p{meta.get('page_start', 0)} "
                f"type={meta.get('chunk_type', '?')} "
                f"tag={meta.get('layout_tag', '')} "
                f"text={doc.page_content[:100].replace(chr(10), ' ')}"
            )

    def _log_metrics(
        self,
        query: str,
        top_k: int,
        total_found: int,
        reranked: bool,
        timings: dict[str, float],
    ) -> None:
        """输出检索性能指标（仅在 kb_retrieval_metrics_enabled 时）。"""
        if not self._settings.kb_retrieval_metrics_enabled:
            return
        parts = [
            f"query=\"{query}\"",
            f"top_k={top_k}",
            f"total_found={total_found}",
            f"reranked={reranked}",
        ]
        for step in ("rewrite", "embed", "retrieval", "rerank", "dedup", "context", "total"):
            if step in timings:
                parts.append(f"{step}={timings[step]:.1f}ms")
        logger.info("[检索 Metrics] " + " | ".join(parts))

    def _deduplicate_results(
        self,
        sorted_results: list[tuple[Document, float]],
        top_k: int,
    ) -> list[tuple[Document, float]]:
        """parent 去重 → 分数阈值 → MMR 多样化。"""
        # Phase 1: parent_chunk_id 去重（同 parent 保留最高分）
        best_by_parent: dict[str, tuple[Document, float]] = {}
        standalone: list[tuple[Document, float]] = []

        for doc, score in sorted_results:
            meta = doc.metadata or {}
            parent_id = meta.get("parent_chunk_id") or ""
            chunk_id = meta.get("chunk_id", "")
            if parent_id and parent_id != chunk_id:
                if parent_id not in best_by_parent or score > best_by_parent[parent_id][1]:
                    best_by_parent[parent_id] = (doc, score)
            else:
                standalone.append((doc, score))

        merged = list(best_by_parent.values()) + standalone
        merged.sort(key=lambda x: x[1], reverse=True)

        # Phase 2: 分数阈值
        min_score = self._settings.kb_rerank_min_score
        filtered = [(d, s) for d, s in merged if s >= min_score]

        if not filtered:
            return []

        # Phase 3: MMR 多样化
        if self._settings.kb_search_mmr_enabled and len(filtered) > 1:
            return self._mmr_select(filtered, top_k, self._settings.kb_search_mmr_lambda)

        return filtered[:top_k]

    @staticmethod
    def _char_ngrams(text: str, n: int = 3) -> set[str]:
        cleaned = text.replace(" ", "").replace("\n", "")
        if len(cleaned) < n:
            return {cleaned} if cleaned else set()
        return {cleaned[i : i + n] for i in range(len(cleaned) - n + 1)}

    @classmethod
    def _jaccard(cls, a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        inter = len(a & b)
        union = len(a | b)
        return inter / union if union else 0.0

    @classmethod
    def _mmr_select(
        cls,
        candidates: list[tuple[Document, float]],
        top_k: int,
        lambda_: float,
    ) -> list[tuple[Document, float]]:
        """MMR 多样化选择。"""
        selected: list[tuple[Document, float]] = []
        remaining = list(candidates)
        ngram_cache = {id(doc): cls._char_ngrams(doc.page_content) for doc, _ in candidates}

        while len(selected) < top_k and remaining:
            best_idx = 0
            best_mmr = float("-inf")
            for i, (doc, score) in enumerate(remaining):
                max_sim = 0.0
                if selected:
                    ng = ngram_cache[id(doc)]
                    max_sim = max(
                        cls._jaccard(ng, ngram_cache[id(s[0])]) for s in selected
                    )
                mmr = lambda_ * score - (1.0 - lambda_) * max_sim
                if mmr > best_mmr:
                    best_mmr = mmr
                    best_idx = i
            selected.append(remaining.pop(best_idx))

        return selected

    async def _validate_index_model(
        self, collection_name: str, tenant_id: str, expected_model: str
    ) -> None:
        indexed_model = await self._vector_store.get_collection_embedding_model(
            collection_name, tenant_id
        )
        if indexed_model and indexed_model != expected_model:
            raise ValidationError(
                "Embedding 模型与索引不一致，请重建索引后再检索",
                detail={
                    "error": "EMBEDDING_MODEL_MISMATCH",
                    "indexed_model": indexed_model,
                    "current_model": expected_model,
                    "message": "请点击「重建索引」或重新上传文档",
                },
            )

    @staticmethod
    def _doc_score(doc: Document, default: float = 1.0) -> float:
        meta = doc.metadata or {}
        if meta.get("score") is not None:
            return float(meta["score"])
        if meta.get("bm25_score") is not None:
            return float(meta["bm25_score"])
        if meta.get("distance") is not None:
            return max(0.0, 1.0 - float(meta["distance"]))
        return default

    @staticmethod
    def _build_vector_filter(filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None
        vector_filter: dict[str, Any] = {}
        if "document_id" in filters:
            vector_filter["document_id"] = filters["document_id"]
        if "chunk_type" in filters:
            vector_filter["chunk_type"] = filters["chunk_type"]
        return vector_filter or None

    # ── 批量上下文预加载（消除 N+1 DB 查询）────────────────

    @staticmethod
    async def _batch_load_doc_info(
        doc_ids: list[str],
        tenant_id: str,
        doc_repo: Any,
    ) -> dict[str, tuple[str, str, str]]:
        """批量加载文档基本信息，一次 SQL 覆盖所有 doc_id。

        返回 {doc_id: (filename, file_type, stored_path)} 映射。
        """
        from sqlalchemy import select

        from src.models.domain.knowledge_base import KBDocument

        if not doc_ids:
            return {}

        stmt = select(KBDocument).where(
            KBDocument.id.in_(doc_ids),
            KBDocument.tenant_id == tenant_id,
        )
        result = await doc_repo._session.execute(stmt)
        docs = result.scalars().all()
        return {
            d.id: (d.filename, d.file_type or "unknown", d.stored_path or "")
            for d in docs
        }

    async def _batch_load_adjacent_chunks(
        self,
        positions: list[tuple[str, int]],
        tenant_id: str,
    ) -> dict[tuple[str, int], tuple[str | None, str | None]]:
        """批量加载相邻 chunk（前后各一），一次 SQL IN + OR 覆盖全部位置。

        返回 {(doc_id, chunk_index): (before_content, after_content)} 映射。
        """
        from sqlalchemy import or_, select

        from src.models.domain.knowledge_base import KBChunk

        if not positions:
            return {}

        # 构造 (document_id = ? AND chunk_index = ?) OR ... 条件
        conditions = [
            (KBChunk.document_id == did) & (KBChunk.chunk_index == idx)
            for did, idx in positions
            for idx in (idx - 1, idx + 1)  # 每条结果的前后位置
        ]
        if not conditions:
            return {}

        stmt = select(KBChunk).where(
            or_(*conditions),
            KBChunk.tenant_id == tenant_id,
            KBChunk.is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        chunks = result.scalars().all()

        # 构建快速查找: {(doc_id, chunk_index): content}
        chunk_map: dict[tuple[str, int], str] = {
            (c.document_id, c.chunk_index): c.content for c in chunks
        }

        # 组装结果
        adjacent_map: dict[tuple[str, int], tuple[str | None, str | None]] = {}
        for did, ci in positions:
            before = chunk_map.get((did, ci - 1))
            after = chunk_map.get((did, ci + 1))
            adjacent_map[(did, ci)] = (before, after)

        return adjacent_map

    async def _batch_load_parent_contexts(
        self,
        parent_ids: list[str],
        tenant_id: str,
    ) -> dict[str, str]:
        """批量加载 parent chunk 的兄弟内容，一次 SQL IN 覆盖全部 parent。

        返回 {parent_chunk_id: joined_sibling_content} 映射。
        """
        from sqlalchemy import select

        from src.models.domain.knowledge_base import KBChunk

        if not parent_ids:
            return {}

        stmt = (
            select(KBChunk)
            .where(
                KBChunk.parent_chunk_id.in_(parent_ids),
                KBChunk.tenant_id == tenant_id,
                KBChunk.is_deleted == False,  # noqa: E712
            )
            .order_by(KBChunk.chunk_index)
        )
        result = await self._session.execute(stmt)
        siblings = result.scalars().all()

        # 按 parent_chunk_id 分组
        groups: dict[str, list[str]] = {}
        for c in siblings:
            pid = c.parent_chunk_id
            if pid is None:
                continue
            if pid not in groups:
                groups[pid] = []
            groups[pid].append(c.content)

        return {pid: "\n".join(contents) for pid, contents in groups.items()}
