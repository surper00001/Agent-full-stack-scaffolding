"""
RAG 检索编排管道。

职责：embed → 向量检索 → (可选) 混合检索 → rerank → 去重/MMR → 上下文扩展。
"""

from __future__ import annotations

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
    from src.vectorstore.chroma_store import ChromaVectorStore


class RetrievalPipeline:
    """知识库检索管道——编排向量检索与精排。"""

    def __init__(
        self,
        session: AsyncSession,
        vector_store: ChromaVectorStore,
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
    ) -> dict[str, Any]:
        """执行完整检索流程（含全链路日志）。"""
        # ═══ Step 1: Query ═══
        logger.info(f"[检索 Step1] query='{query[:120]}' top_k={top_k} rerank={rerank}")

        embedding_model = kb.embedding_model or self._settings.kb_embedding_model
        reranker_model = kb.reranker_model or self._settings.kb_reranker_model
        strategy = get_embedding_strategy(embedding_model)

        await self._validate_index_model(collection_name, tenant_id, embedding_model)

        search_k = min(top_k * 5 if rerank else top_k, 50)
        chroma_filter = self._build_chroma_filter(filters)

        from src.services.embedding_service import get_embedding_service
        from src.services.reranker_service import get_reranker_service

        embedding_svc = get_embedding_service(embedding_model)
        query_vector = await embedding_svc.embed_query(query, strategy=strategy)

        # ═══ Step 2: Top-K Retrieval ═══
        hybrid_used = (
            self._hybrid_search is not None
            and self._settings.kb_hybrid_search_enabled
        )
        try:
            if hybrid_used:
                from src.db.repository import BaseRepository
                from src.models.domain.knowledge_base import KBChunk

                chunk_repo = BaseRepository[KBChunk](KBChunk, self._session)
                results = await self._hybrid_search.search(
                    kb_id=kb.id,
                    tenant_id=tenant_id,
                    query=query,
                    query_vector=query_vector,
                    collection_name=collection_name,
                    top_k=search_k,
                    chroma_filter=chroma_filter,
                    chunk_repo=chunk_repo,
                )
            else:
                results = await self._vector_store.similarity_search_by_vector(
                    query_embedding=query_vector,
                    collection_name=collection_name,
                    tenant_id=tenant_id,
                    top_k=search_k,
                    filter=chroma_filter,
                )
        except VectorStoreError:
            raise
        except Exception as e:
            logger.error(f"向量检索失败: {e}")
            raise VectorStoreError(f"向量检索失败: {e}") from e

        total_found = len(results)
        logger.info(
            f"[检索 Step2] 粗排完成: total_found={total_found} "
            f"mode={'hybrid' if hybrid_used else 'vector'}"
        )
        if results:
            self._log_top_results(results[:8], "Step2 粗排样本")

        if not results:
            return {"query": query, "results": [], "total_found": 0, "reranked": False}

        # ═══ Step 3: Rerank ═══
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

        # ═══ Step 4: Dedup + MMR ═══
        pre_dedup_count = len(sorted_results)
        sorted_results = self._deduplicate_results(sorted_results, top_k)
        logger.info(
            f"[检索 Step4] 去重/MMR: {pre_dedup_count} → {len(sorted_results)} "
            f"(target top_k={top_k})"
        )
        if sorted_results:
            self._log_top_results(sorted_results, "Step4 精排结果")

        doc_info_cache: dict[str, tuple[str, str, str]] = {}
        search_results: list[dict[str, Any]] = []

        for doc, score in sorted_results:
            meta = doc.metadata or {}
            chunk_id = meta.get("chunk_id", "")
            doc_id = meta.get("document_id", "")

            doc_filename = "未知文件"
            doc_file_type = "unknown"
            stored_path = ""
            if doc_repo is not None and doc_id:
                try:
                    if doc_id not in doc_info_cache:
                        source_doc = await doc_repo.get_by_id_with_tenant(doc_id, tenant_id)
                        if source_doc:
                            doc_info_cache[doc_id] = (
                                source_doc.filename,
                                source_doc.file_type,
                                source_doc.stored_path,
                            )
                    if doc_id in doc_info_cache:
                        doc_filename, doc_file_type, stored_path = doc_info_cache[doc_id]
                except Exception:
                    pass

            image_path = meta.get("image_path") or ""
            image_url = build_image_url(kb.id, doc_id, image_path, stored_path)

            context_before, context_after = await self._get_adjacent_chunks(
                doc_id, meta.get("chunk_index", 0), tenant_id
            )
            parent_context = await self._expand_parent_chunk(
                meta.get("parent_chunk_id"), doc.page_content, tenant_id
            )

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
                    "ocr_status": meta.get("ocr_status", ""),
                    "ocr_error": meta.get("ocr_error", ""),
                    "image_caption": meta.get("image_caption", ""),
                    "image_description": meta.get("image_description", ""),
                    "section_title": meta.get("section_title", ""),
                    "section_path": meta.get("section_path", ""),
                    "content_summary": meta.get("content_summary", ""),
                    "doc_category": meta.get("doc_category", ""),
                    "layout_tag": meta.get("layout_tag", ""),
                    "bbox": meta.get("bbox"),
                    "parent_context": parent_context if parent_context != doc.page_content else "",
                },
                "context_before": context_before,
                "context_after": context_after,
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
            f"sources={list(zip(final_sources, final_pages))}"
        )

        return {
            "query": query,
            "results": search_results,
            "total_found": total_found,
            "reranked": rerank,
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
    def _build_chroma_filter(filters: dict[str, Any] | None) -> dict[str, Any] | None:
        if not filters:
            return None
        chroma_filter: dict[str, Any] = {}
        if "document_id" in filters:
            chroma_filter["document_id"] = filters["document_id"]
        if "chunk_type" in filters:
            chroma_filter["chunk_type"] = filters["chunk_type"]
        return chroma_filter or None

    async def _get_adjacent_chunks(
        self, doc_id: str, chunk_index: int, tenant_id: str
    ) -> tuple[str | None, str | None]:
        from sqlalchemy import and_, select

        from src.models.domain.knowledge_base import KBChunk

        stmt_before = select(KBChunk).where(
            and_(
                KBChunk.document_id == doc_id,
                KBChunk.chunk_index == chunk_index - 1,
                KBChunk.tenant_id == tenant_id,
                KBChunk.is_deleted == False,  # noqa: E712
            )
        )
        result_before = await self._session.execute(stmt_before)
        chunk_before = result_before.scalar_one_or_none()

        stmt_after = select(KBChunk).where(
            and_(
                KBChunk.document_id == doc_id,
                KBChunk.chunk_index == chunk_index + 1,
                KBChunk.tenant_id == tenant_id,
                KBChunk.is_deleted == False,  # noqa: E712
            )
        )
        result_after = await self._session.execute(stmt_after)
        chunk_after = result_after.scalar_one_or_none()

        return (
            chunk_before.content if chunk_before else None,
            chunk_after.content if chunk_after else None,
        )

    async def _expand_parent_chunk(
        self,
        parent_chunk_id: str | None,
        fallback_content: str,
        tenant_id: str,
    ) -> str:
        if not parent_chunk_id:
            return fallback_content

        from sqlalchemy import and_, select

        from src.models.domain.knowledge_base import KBChunk

        stmt = (
            select(KBChunk)
            .where(
                and_(
                    KBChunk.parent_chunk_id == parent_chunk_id,
                    KBChunk.tenant_id == tenant_id,
                    KBChunk.is_deleted == False,  # noqa: E712
                )
            )
            .order_by(KBChunk.chunk_index)
        )
        result = await self._session.execute(stmt)
        siblings = result.scalars().all()
        if siblings:
            return "\n".join(c.content for c in siblings)
        return fallback_content
