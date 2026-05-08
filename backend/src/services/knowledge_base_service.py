"""
知识库服务——Agentic RAG 核心编排器。

协调文档分析 → 解析 → 智能分块 → 向量化 → 索引的完整生命周期。
提供实时进度追踪和预估时间。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document as LangchainDocument
from loguru import logger

from src.core.config import get_settings
from src.core.exceptions import DeletionError, NotFoundError, ValidationError
from src.db.repository import BaseRepository
from src.models.domain.knowledge_base import KBChunk, KBDocument, KnowledgeBase
from src.services.chunking_service import ChunkingService
from src.services.document_processor import DocumentProcessor
from src.services.embedding_service import EmbeddingService, get_embedding_service
from src.services.file_storage import FileStorageService
from src.services.processing_progress import (
    ProcessingProgressTracker,
    ProcessStage,
)
from src.services.rag.hybrid_search_service import HybridSearchService
from src.services.rag.retrieval_pipeline import RetrievalPipeline
from src.services.reranker_service import RerankerService, get_reranker_service
from src.vectorstore.chroma_store import ChromaVectorStore

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.services.document_analyzer import DocStructure


class KnowledgeBaseService:
    """知识库业务编排服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._kb_repo = BaseRepository[KnowledgeBase](KnowledgeBase, session)
        self._doc_repo = BaseRepository[KBDocument](KBDocument, session)
        self._chunk_repo = BaseRepository[KBChunk](KBChunk, session)
        self._file_storage = FileStorageService()
        self._doc_processor = DocumentProcessor(self._file_storage)
        self._settings = get_settings()
        self._progress = ProcessingProgressTracker.get_instance()
        self._vector_store: ChromaVectorStore | None = None
        self._hybrid_search: HybridSearchService | None = None
        self._retrieval: RetrievalPipeline | None = None

    def _get_embedding_service(self, model_name: str | None = None) -> EmbeddingService:
        return get_embedding_service(model_name)

    @property
    def embeddings(self) -> EmbeddingService:
        return get_embedding_service()

    @property
    def reranker(self) -> RerankerService:
        return get_reranker_service()

    @property
    def vector_store(self) -> ChromaVectorStore:
        if self._vector_store is None:
            self._vector_store = ChromaVectorStore(
                embedding_function=self.embeddings.to_langchain()
            )
        return self._vector_store

    @property
    def retrieval(self) -> RetrievalPipeline:
        if self._retrieval is None:
            if self._hybrid_search is None:
                self._hybrid_search = HybridSearchService(self.vector_store)
            self._retrieval = RetrievalPipeline(
                self._session, self.vector_store, self._hybrid_search
            )
        return self._retrieval

    _EMBED_TEXT_MAX_CHARS = 2048

    @staticmethod
    def _truncate_embed_text(text: str, max_chars: int = 2048) -> str:
        """在中文句号处安全截断 embedding 输入文本。"""
        if len(text) <= max_chars:
            return text
        truncated = text[:max_chars]
        for punct in ("。", "！", "？", ".", "!", "?"):
            idx = truncated.rfind(punct)
            if idx > max_chars // 2:
                return truncated[: idx + 1]
        return truncated

    @classmethod
    def _build_embed_text(cls, chunk: Any) -> str:
        """索引时拼接结构化信号，提升按章节名/概念召回能力。"""
        parts: list[str] = []
        if chunk.section_path:
            parts.append(f"章节: {chunk.section_path}")
        if chunk.section_title:
            parts.append(f"标题: {chunk.section_title}")
        if chunk.content_summary:
            parts.append(f"摘要: {chunk.content_summary}")
        parts.append(chunk.content)
        full = "\n".join(parts)
        if len(full) > cls._EMBED_TEXT_MAX_CHARS:
            from loguru import logger

            logger.warning(
                f"embedding 文本超长已截断: chunk={getattr(chunk, 'chunk_id', '?')} "
                f"len={len(full)} max={cls._EMBED_TEXT_MAX_CHARS}"
            )
            return cls._truncate_embed_text(full, cls._EMBED_TEXT_MAX_CHARS)
        return full

    def _kb_collection_name(self, kb_id: str) -> str:
        return f"kb_{kb_id}"

    _VECTOR_DELETE_BATCH = 500

    async def _purge_document_vectors(
        self, doc_id: str, kb_id: str, tenant_id: str
    ) -> None:
        """删除文档在向量库中的全部条目（按 ID + document_id 双保险）。"""
        chunks = await self._chunk_repo.list_all(
            tenant_id=tenant_id, document_id=doc_id, limit=100_000
        )
        vector_ids = [c.vector_id for c in chunks if c.vector_id]
        collection = self._kb_collection_name(kb_id)
        try:
            for i in range(0, len(vector_ids), self._VECTOR_DELETE_BATCH):
                batch = vector_ids[i : i + self._VECTOR_DELETE_BATCH]
                if batch:
                    await self.vector_store.delete_by_ids(
                        batch, collection, tenant_id
                    )
            await self.vector_store.delete_by_filter(
                {"document_id": doc_id}, collection, tenant_id
            )
        except Exception as e:
            logger.error(f"删除文档向量失败 doc_id={doc_id}: {e}")
            raise DeletionError(f"删除向量数据失败: {e}") from e

    async def _purge_document(
        self,
        doc: KBDocument,
        kb: KnowledgeBase,
        tenant_id: str,
    ) -> None:
        """级联清理单文档：向量 → 磁盘 → chunk 物理删 → 文档软删。"""
        await self._purge_document_vectors(doc.id, kb.id, tenant_id)

        try:
            await asyncio.to_thread(
                self._file_storage.delete_document_assets,
                tenant_id,
                kb.user_id,
                kb.id,
                doc.id,
                doc.stored_path,
            )
        except Exception as e:
            logger.error(f"删除文档文件失败 doc_id={doc.id}: {e}")
            raise DeletionError(f"删除文档文件失败: {e}") from e

        removed = await self._chunk_repo.hard_delete_by_filter(
            tenant_id=tenant_id, document_id=doc.id
        )
        logger.info(f"已物理删除 {removed} 个 chunk, doc_id={doc.id}")

        kb.document_count = max(0, kb.document_count - 1)
        kb.total_chunks = max(0, kb.total_chunks - doc.chunk_count)
        kb.total_size_bytes = max(0, kb.total_size_bytes - doc.file_size)
        await self._kb_repo.update(kb)

        await self._doc_repo.soft_delete(doc.id)
        self._progress.cleanup(doc.id)

    # ========== 进度查询 ==========

    def get_document_progress(self, doc_id: str) -> dict[str, Any] | None:
        """查询文档处理进度（供 API 轮询）。"""
        snap = self._progress.get_progress(doc_id)
        if snap is None:
            return None
        return {
            "document_id": doc_id,
            "stage": snap.stage.value,
            "stage_label": snap.label,
            "percentage": round(snap.percentage * 100, 1),
            "estimated_seconds": (
                round(snap.estimated_seconds, 1) if snap.estimated_seconds else None
            ),
            "file_size_bytes": snap.file_size_bytes,
            "error_message": snap.error_message,
            "total_pages": snap.total_pages,
            "parsed_pages": snap.parsed_pages,
            "text_blocks": snap.text_blocks,
            "table_blocks": snap.table_blocks,
            "image_blocks": snap.image_blocks,
            "total_chunks": snap.total_chunks,
            "embedded_chunks": snap.embedded_chunks,
        }

    # ========== 知识库 CRUD ==========

    async def create_kb(
        self,
        name: str,
        user_id: str,
        tenant_id: str,
        description: str | None = None,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        embedding_model: str | None = None,
        reranker_model: str | None = None,
    ) -> KnowledgeBase:
        embedding_model = embedding_model or self._settings.kb_embedding_model
        reranker_model = reranker_model or self._settings.kb_reranker_model
        kb = KnowledgeBase(
            name=name,
            description=description,
            user_id=user_id,
            tenant_id=tenant_id,
            chunk_size=chunk_size or self._settings.kb_default_chunk_size,
            chunk_overlap=chunk_overlap or self._settings.kb_default_chunk_overlap,
            embedding_model=embedding_model,
            reranker_model=reranker_model,
        )
        return await self._kb_repo.create(kb)

    async def get_kb(self, kb_id: str, tenant_id: str) -> KnowledgeBase:
        kb = await self._kb_repo.get_by_id_with_tenant(kb_id, tenant_id)
        if kb is None:
            raise NotFoundError(f"知识库不存在: {kb_id}")
        return kb

    async def list_kbs(
        self, user_id: str, tenant_id: str, skip: int = 0, limit: int = 20
    ) -> list[KnowledgeBase]:
        return await self._kb_repo.list_all(
            tenant_id=tenant_id, user_id=user_id, skip=skip, limit=limit
        )

    async def count_kbs(self, user_id: str, tenant_id: str) -> int:
        return await self._kb_repo.count(tenant_id=tenant_id, user_id=user_id)

    async def update_kb(
        self, kb_id: str, tenant_id: str, **updates: Any
    ) -> KnowledgeBase:
        kb = await self.get_kb(kb_id, tenant_id)
        for field, value in updates.items():
            if value is not None and hasattr(kb, field):
                setattr(kb, field, value)
        return await self._kb_repo.update(kb)

    async def delete_kb(self, kb_id: str, tenant_id: str, user_id: str) -> None:
        kb = await self.get_kb(kb_id, tenant_id)
        docs = await self._doc_repo.list_all(
            tenant_id=tenant_id, knowledge_base_id=kb_id, limit=10_000
        )

        collection_deleted = False
        try:
            await self.vector_store.delete_collection(
                self._kb_collection_name(kb_id), tenant_id
            )
            collection_deleted = True
        except Exception as e:
            logger.warning(f"删除向量集合失败，将逐文档清理: {e}")

        if not collection_deleted:
            for doc in docs:
                await self._purge_document_vectors(doc.id, kb_id, tenant_id)

        try:
            await asyncio.to_thread(
                self._file_storage.delete_kb_files, tenant_id, user_id, kb_id
            )
        except Exception as e:
            logger.error(f"删除知识库文件失败 kb_id={kb_id}: {e}")
            raise DeletionError(f"删除知识库文件失败: {e}") from e

        await self._chunk_repo.soft_delete_by_filter(
            tenant_id=tenant_id, knowledge_base_id=kb_id
        )
        await self._doc_repo.soft_delete_by_filter(
            tenant_id=tenant_id, knowledge_base_id=kb_id
        )
        for doc in docs:
            self._progress.cleanup(doc.id)

        await self._kb_repo.soft_delete(kb.id)

    # ========== 文档管理 ==========

    async def upload_document(
        self,
        kb_id: str,
        filename: str,
        file_content: bytes,
        tenant_id: str,
        user_id: str,
    ) -> KBDocument:
        _ = await self.get_kb(kb_id, tenant_id)

        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        file_type = f".{ext}" if ext else "unknown"
        if file_type not in self._settings.kb_supported_extensions:
            raise ValidationError(f"不支持的文件类型: {file_type}")

        max_bytes = self._settings.kb_max_file_size_mb * 1024 * 1024
        if len(file_content) > max_bytes:
            raise ValidationError(
                f"文件过大: {len(file_content) / 1024 / 1024:.1f}MB "
                f"(最大 {self._settings.kb_max_file_size_mb}MB)"
            )

        doc = KBDocument(
            knowledge_base_id=kb_id,
            filename=filename,
            stored_path="",
            file_size=len(file_content),
            file_type=file_type.lstrip("."),
            tenant_id=tenant_id,
            status="uploading",
        )
        doc = await self._doc_repo.create(doc)

        stored_path = self._file_storage.save_file(
            tenant_id, user_id, kb_id, doc.id, filename, file_content
        )
        doc.stored_path = stored_path
        await self._doc_repo.update(doc)

        # 初始化进度追踪
        self._progress.start(doc.id, len(file_content))

        logger.info(f"文档已上传: {doc.id} ({filename}), 大小: {len(file_content)} bytes")
        return doc

    async def process_document(
        self, doc_id: str, kb_id: str, tenant_id: str, _user_id: str
    ) -> None:
        """处理文档：分析 → 解析 → 智能分块 → 向量化 → 索引（后台任务）。

        每阶段更新进度追踪器，供前端轮询。
        """
        doc = await self._doc_repo.get_by_id_with_tenant(doc_id, tenant_id)
        if doc is None:
            raise NotFoundError(f"文档不存在: {doc_id}")

        doc_structure: DocStructure | None = None  # type: ignore[name-defined]

        try:
            # ---- 阶段 1: 文档结构分析 ----
            doc.status = "processing"
            await self._doc_repo.update(doc)
            self._progress.set_stage(doc_id, ProcessStage.ANALYZING)

            kb = await self.get_kb(kb_id, tenant_id)

            # ---- 阶段 2: 文档解析 ----
            self._progress.set_stage(doc_id, ProcessStage.PARSING)

            import asyncio
            blocks, page_count, metadata, doc_structure = await asyncio.to_thread(
                self._doc_processor.process,
                doc.stored_path,
                tenant_id=tenant_id,
                user_id=kb.user_id,
                kb_id=kb_id,
                doc_id=doc_id,
            )

            # 统计解析结果并报告详情
            text_count = sum(1 for b in blocks if b.block_type == "text")
            table_count = sum(1 for b in blocks if b.block_type == "table")
            image_count = sum(1 for b in blocks if b.block_type == "image")
            self._progress.set_parse_detail(
                doc_id,
                total_pages=page_count,
                text_blocks=text_count,
                table_blocks=table_count,
                image_blocks=image_count,
            )

            doc.page_count = page_count
            doc.metadata_ = {
                **(metadata or {}),
                "doc_category": doc_structure.category.value,
                "doc_category_label": doc_structure.extra_metadata.get("category_label", "通用"),
                "doc_confidence": doc_structure.confidence,
                "detected_lang": doc_structure.detected_lang,
                "headings": [
                    {"level": h.level, "title": h.title, "page": h.page}
                    for h in doc_structure.headings[:20]
                ],
            }
            await self._doc_repo.update(doc)

            # ---- 阶段 3: 智能分块 ----
            self._progress.set_stage(doc_id, ProcessStage.CHUNKING)

            chunker = ChunkingService(
                child_chunk_size=kb.chunk_size,
                child_chunk_overlap=kb.chunk_overlap,
                parent_chunk_size=self._settings.kb_parent_chunk_size,
                parent_chunk_overlap=self._settings.kb_parent_chunk_overlap,
                doc_structure=doc_structure,
            )
            chunks = chunker.chunk_blocks(blocks, doc_structure)
            self._progress.set_total_chunks(doc_id, len(chunks))
            self._progress.update_chunk(doc_id, len(chunks))

            # ---- 阶段 4: 向量化（使用 KB 绑定的 Qwen3/BGE 模型 + 结构化 enrich） ----
            self._progress.set_stage(doc_id, ProcessStage.EMBEDDING)

            embedding_model = kb.embedding_model or self._settings.kb_embedding_model
            embedding_svc = self._get_embedding_service(embedding_model)
            chunk_texts = [self._build_embed_text(c) for c in chunks]
            batch_size = 32
            all_embeddings: list[list[float]] = []
            total_chunks = len(chunk_texts)
            for batch_start in range(0, total_chunks, batch_size):
                batch = chunk_texts[batch_start : batch_start + batch_size]
                batch_embeddings = await embedding_svc.embed_documents(batch)
                all_embeddings.extend(batch_embeddings)
                done = min(batch_start + batch_size, total_chunks)
                self._progress.update_embed(doc_id, done)

            # ---- 阶段 5: 索引（metadata 写入 embedding_model 版本标记） ----
            self._progress.set_stage(doc_id, ProcessStage.INDEXING)

            chunk_ids = [c.chunk_id for c in chunks]
            langchain_docs: list[LangchainDocument] = []
            kb_chunks: list[KBChunk] = []

            for chunk in chunks:
                lc_doc = LangchainDocument(
                    page_content=chunk.content,
                    metadata={
                        "chunk_id": chunk.chunk_id,
                        "document_id": doc_id,
                        "kb_id": kb_id,
                        "chunk_index": chunk.chunk_index,
                        "page_start": chunk.page_start,
                        "page_end": chunk.page_end,
                        "chunk_type": chunk.chunk_type,
                        "parent_chunk_id": chunk.parent_chunk_id or "",
                        "table_html": chunk.table_html or "",
                        "image_path": chunk.image_path or "",
                        "ocr_status": chunk.ocr_status or "",
                        "ocr_error": chunk.ocr_error or "",
                        "image_caption": chunk.image_caption or "",
                        "image_description": chunk.image_description or "",
                        "section_title": chunk.section_title or "",
                        "section_path": chunk.section_path or "",
                        "content_summary": chunk.content_summary or "",
                        **(
                            {"bbox": list(chunk.bbox)}
                            if chunk.bbox
                            else {}
                        ),
                        "is_heading": chunk.is_heading,
                        "heading_level": chunk.heading_level,
                        "doc_category": chunk.doc_category or "",
                        "embedding_model": embedding_model,
                    },
                )
                langchain_docs.append(lc_doc)

                kb_chunk = KBChunk(
                    document_id=doc_id,
                    knowledge_base_id=kb_id,
                    content=chunk.content,
                    chunk_index=chunk.chunk_index,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    chunk_type=chunk.chunk_type,
                    parent_chunk_id=chunk.parent_chunk_id,
                    vector_id=chunk.chunk_id,
                    tenant_id=tenant_id,
                    metadata_={
                        "bbox": list(chunk.bbox) if chunk.bbox else None,
                        "table_html": chunk.table_html,
                        "image_path": chunk.image_path,
                        "image_caption": chunk.image_caption,
                        "image_description": chunk.image_description,
                        "section_title": chunk.section_title,
                        "section_path": chunk.section_path,
                        "ocr_status": chunk.ocr_status,
                        "ocr_error": chunk.ocr_error,
                        "content_summary": chunk.content_summary,
                        "is_heading": chunk.is_heading,
                        "heading_level": chunk.heading_level,
                        "doc_category": chunk.doc_category,
                    },
                )
                kb_chunks.append(kb_chunk)

            collection_name = self._kb_collection_name(kb_id)
            await self.vector_store.add_documents_with_embeddings(
                documents=langchain_docs,
                embeddings=all_embeddings,
                ids=chunk_ids,
                collection_name=collection_name,
                tenant_id=tenant_id,
            )

            if self._hybrid_search:
                self._hybrid_search.invalidate_cache(kb_id, tenant_id)

            for kb_chunk in kb_chunks:
                self._session.add(kb_chunk)
            await self._session.flush()

            # ---- 完成 ----
            doc.chunk_count = len(chunks)
            doc.status = "ready"
            await self._doc_repo.update(doc)

            kb.document_count += 1
            kb.total_chunks += len(chunks)
            kb.total_size_bytes += doc.file_size
            await self._kb_repo.update(kb)

            self._progress.set_ready(doc_id)

            text_chunks = sum(1 for c in chunks if c.chunk_type == "text")
            table_chunks = sum(1 for c in chunks if c.chunk_type == "table")
            image_chunks = sum(1 for c in chunks if c.chunk_type == "image")
            code_chunks = sum(1 for c in chunks if c.chunk_type == "code")
            parent_ids = len({c.parent_chunk_id for c in chunks if c.parent_chunk_id})

            logger.info(
                f"文档处理完成: {doc_id}, 类型={doc_structure.category.value if doc_structure else 'N/A'}, "
                f"页数={page_count}, 总分块={len(chunks)} "
                f"(文本={text_chunks}, 表格={table_chunks}, 图片={image_chunks}, 代码={code_chunks}), "
                f"父块={parent_ids}"
            )

        except Exception as e:
            logger.error(f"文档处理失败: {doc_id} - {e}")
            self._progress.set_error(doc_id, str(e))
            doc.status = "error"
            doc.error_message = str(e)
            await self._doc_repo.update(doc)
            await self._session.commit()
            raise

    async def prepare_reprocess(self, doc_id: str, kb_id: str, tenant_id: str) -> None:
        """校验并重置文档状态，供后台重新处理。"""
        doc = await self._doc_repo.get_by_id_with_tenant(doc_id, tenant_id)
        if doc is None or doc.knowledge_base_id != kb_id:
            raise NotFoundError(f"文档不存在: {doc_id}")

        snap = self._progress.get_progress(doc_id)
        active_stages = {
            ProcessStage.UPLOADED,
            ProcessStage.ANALYZING,
            ProcessStage.PARSING,
            ProcessStage.CHUNKING,
            ProcessStage.EMBEDDING,
            ProcessStage.INDEXING,
        }
        if snap is not None and snap.stage in active_stages:
            raise ValidationError("文档正在处理中，请稍后再试")

        doc.status = "processing"
        doc.error_message = None
        await self._doc_repo.update(doc)
        self._progress.start(doc_id, doc.file_size or 0)

    async def get_document(self, doc_id: str, tenant_id: str) -> KBDocument:
        doc = await self._doc_repo.get_by_id_with_tenant(doc_id, tenant_id)
        if doc is None:
            raise NotFoundError(f"文档不存在: {doc_id}")
        return doc

    async def list_documents(
        self, kb_id: str, tenant_id: str, skip: int = 0, limit: int = 50
    ) -> list[KBDocument]:
        return await self._doc_repo.list_all(
            tenant_id=tenant_id, knowledge_base_id=kb_id, skip=skip, limit=limit
        )

    async def count_documents(self, kb_id: str, tenant_id: str) -> int:
        return await self._doc_repo.count(tenant_id=tenant_id, knowledge_base_id=kb_id)

    async def delete_document(
        self, doc_id: str, kb_id: str, tenant_id: str, _user_id: str
    ) -> None:
        doc = await self.get_document(doc_id, tenant_id)
        kb = await self.get_kb(kb_id, tenant_id)
        await self._purge_document(doc, kb, tenant_id)

    # ========== 检索 ==========

    async def search(
        self,
        kb_id: str,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        rerank: bool = True,
        filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """搜索知识库——委托 RetrievalPipeline 执行完整检索链路。

        支持 Redis 缓存：相同查询在 TTL 内直接返回缓存结果。
        """
        kb = await self.get_kb(kb_id, tenant_id)

        # 检查 Redis 缓存
        if self._settings.kb_search_cache_enabled:
            try:
                from src.services.redis_service import RedisService
                redis = await RedisService.get_instance()
                if redis.available:
                    cached = await redis.get_search_result(kb_id, query, top_k)
                    if cached:
                        logger.debug("Search cache hit: kb={}, query={}", kb_id, query[:50])
                        return cached
            except Exception as e:
                logger.debug("Redis cache check failed: {}", e)

        result = await self.retrieval.search(
            kb=kb,
            query=query,
            tenant_id=tenant_id,
            collection_name=self._kb_collection_name(kb_id),
            top_k=top_k,
            rerank=rerank,
            filters=filters,
            doc_repo=self._doc_repo,
        )

        # 写入 Redis 缓存
        if self._settings.kb_search_cache_enabled:
            try:
                from src.services.redis_service import RedisService
                redis = await RedisService.get_instance()
                if redis.available:
                    await redis.set_search_result(
                        kb_id, query, top_k, result,
                        ttl=self._settings.kb_search_cache_ttl,
                    )
            except Exception as e:
                logger.debug("Redis cache write failed: {}", e)

        return result

    async def reindex_kb(self, kb_id: str, tenant_id: str) -> dict[str, Any]:
        """重建知识库向量索引——换 Embedding 模型后必须执行。"""
        kb = await self.get_kb(kb_id, tenant_id)
        embedding_model = kb.embedding_model or self._settings.kb_embedding_model
        embedding_svc = self._get_embedding_service(embedding_model)

        docs = await self._doc_repo.list_all(
            tenant_id=tenant_id, knowledge_base_id=kb_id, limit=10000
        )
        ready_docs = [d for d in docs if d.status == "ready"]
        reindexed = 0
        total_chunks = 0

        for doc in ready_docs:
            chunks = await self._chunk_repo.list_all(
                tenant_id=tenant_id, document_id=doc.id, limit=100000
            )
            if not chunks:
                continue

            old_ids = [c.vector_id for c in chunks if c.vector_id]
            if old_ids:
                await self.vector_store.delete_by_ids(
                    old_ids, self._kb_collection_name(kb_id), tenant_id
                )

            chunk_texts = []
            for c in chunks:
                meta = c.metadata_ or {}
                from types import SimpleNamespace

                ns = SimpleNamespace(
                    content=c.content,
                    section_path=meta.get("section_path"),
                    section_title=meta.get("section_title"),
                    content_summary=meta.get("content_summary"),
                )
                chunk_texts.append(self._build_embed_text(ns))

            all_embeddings: list[list[float]] = []
            batch_size = 32
            for batch_start in range(0, len(chunk_texts), batch_size):
                batch = chunk_texts[batch_start : batch_start + batch_size]
                all_embeddings.extend(await embedding_svc.embed_documents(batch))

            langchain_docs = []
            chunk_ids = []
            for chunk in chunks:
                meta = chunk.metadata_ or {}
                chunk_ids.append(chunk.vector_id or chunk.id)
                bbox = meta.get("bbox")
                langchain_docs.append(
                    LangchainDocument(
                        page_content=chunk.content,
                        metadata={
                            "chunk_id": chunk.vector_id or chunk.id,
                            "document_id": doc.id,
                            "kb_id": kb_id,
                            "chunk_index": chunk.chunk_index,
                            "page_start": chunk.page_start,
                            "page_end": chunk.page_end,
                            "chunk_type": chunk.chunk_type,
                            "parent_chunk_id": chunk.parent_chunk_id or "",
                            "table_html": meta.get("table_html") or "",
                            "image_path": meta.get("image_path") or "",
                            "ocr_status": meta.get("ocr_status") or "",
                            "ocr_error": meta.get("ocr_error") or "",
                            "image_caption": meta.get("image_caption") or "",
                            "image_description": meta.get("image_description") or "",
                            **({"bbox": bbox} if bbox else {}),
                            "section_title": meta.get("section_title", ""),
                            "section_path": meta.get("section_path", ""),
                            "content_summary": meta.get("content_summary", ""),
                            "embedding_model": embedding_model,
                        },
                    )
                )

            await self.vector_store.add_documents_with_embeddings(
                documents=langchain_docs,
                embeddings=all_embeddings,
                ids=chunk_ids,
                collection_name=self._kb_collection_name(kb_id),
                tenant_id=tenant_id,
            )
            reindexed += 1
            total_chunks += len(chunks)

        if self._hybrid_search:
            self._hybrid_search.invalidate_cache(kb_id, tenant_id)

        logger.info(f"知识库 {kb_id} 重建索引完成: {reindexed} 文档, {total_chunks} 分块")
        return {
            "kb_id": kb_id,
            "documents_reindexed": reindexed,
            "chunks_reindexed": total_chunks,
            "embedding_model": embedding_model,
        }

    async def check_index_status(self, kb_id: str, tenant_id: str) -> dict[str, Any]:
        """检查索引模型是否与 KB 配置一致。"""
        kb = await self.get_kb(kb_id, tenant_id)
        indexed_model = await self.vector_store.get_collection_embedding_model(
            self._kb_collection_name(kb_id), tenant_id
        )
        current_model = kb.embedding_model or self._settings.kb_embedding_model
        return {
            "indexed_model": indexed_model,
            "current_model": current_model,
            "needs_reindex": bool(indexed_model and indexed_model != current_model),
        }

    # ========== 文档查看 ==========

    async def view_document(self, doc_id: str, tenant_id: str) -> dict[str, Any]:
        doc = await self.get_document(doc_id, tenant_id)
        kb_id = doc.knowledge_base_id

        chunks = await self._chunk_repo.list_all(
            tenant_id=tenant_id, document_id=doc_id, limit=100000
        )
        chunks.sort(key=lambda c: (c.page_start, c.chunk_index))

        pages: dict[int, list[dict]] = {}
        page_dims = (doc.metadata_ or {}).get("page_dimensions") or {}
        for chunk in chunks:
            page = chunk.page_start
            meta = chunk.metadata_ or {}
            image_path = meta.get("image_path")
            pages.setdefault(page, []).append({
                "type": chunk.chunk_type,
                "content": chunk.content,
                "page": page,
                "bbox": meta.get("bbox"),
                "table_html": meta.get("table_html"),
                "image_path": image_path,
                "image_url": self._build_image_url(kb_id, doc_id, image_path, doc.stored_path),
                "ocr_status": meta.get("ocr_status"),
                "ocr_error": meta.get("ocr_error"),
                "image_caption": meta.get("image_caption"),
                "image_description": meta.get("image_description"),
                "section_title": meta.get("section_title"),
                "section_path": meta.get("section_path"),
            })

        total_pages = doc.page_count or max(pages.keys(), default=1)
        page_list = []
        for p in range(1, total_pages + 1):
            dim = page_dims.get(str(p)) or {}
            block_list = pages.get(p, [])
            page_list.append({
                "page_number": p,
                "page_width": dim.get("width"),
                "page_height": dim.get("height"),
                "text_blocks": block_list,
                "has_content": len(block_list) > 0,
            })

        return {
            "document_id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "total_pages": total_pages,
            "pages": page_list,
            "doc_category": doc.metadata_.get("doc_category") if doc.metadata_ else None,
            "doc_category_label": doc.metadata_.get("doc_category_label") if doc.metadata_ else None,
        }

    async def download_source_file(self, doc_id: str, tenant_id: str) -> tuple[bytes, str]:
        doc = await self.get_document(doc_id, tenant_id)
        content = self._file_storage.read_file(doc.stored_path)
        return content, doc.filename

    async def get_document_image(
        self, doc_id: str, tenant_id: str, image_name: str
    ) -> tuple[bytes, str]:
        """读取文档提取的缩略图/内嵌图片。"""
        doc = await self.get_document(doc_id, tenant_id)
        kb = await self.get_kb(doc.knowledge_base_id, tenant_id)

        if ".." in image_name or "/" in image_name or "\\" in image_name:
            from src.core.exceptions import ValidationError
            raise ValidationError("非法图片名称")

        relative_path = str(
            Path(tenant_id) / kb.user_id / doc.knowledge_base_id / "thumbnails" / doc_id / image_name
        )
        content = self._file_storage.read_thumbnail(relative_path)
        ext = image_name.rsplit(".", 1)[-1].lower() if "." in image_name else "png"
        return content, ext

    async def render_page_preview(
        self,
        doc_id: str,
        tenant_id: str,
        page_num: int,
        scale: float = 2.0,
    ) -> tuple[bytes, float, float]:
        """渲染 PDF 指定页为 PNG，返回 (bytes, page_width, page_height)。"""
        doc = await self.get_document(doc_id, tenant_id)
        if doc.file_type.lower() not in ("pdf",):
            raise ValidationError("仅 PDF 文档支持页面预览")

        import asyncio

        return await asyncio.to_thread(
            self._render_pdf_page_sync, doc.stored_path, page_num, scale
        )

    @staticmethod
    def _render_pdf_page_sync(
        stored_path: str, page_num: int, scale: float
    ) -> tuple[bytes, float, float]:
        import fitz

        storage = FileStorageService()
        file_path = storage.get_absolute_path(stored_path)
        pdf_doc = fitz.open(str(file_path))
        try:
            if page_num < 1 or page_num > pdf_doc.page_count:
                raise ValidationError(f"页码超出范围: {page_num}")
            page = pdf_doc[page_num - 1]
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix)
            return pix.tobytes("png"), float(page.rect.width), float(page.rect.height)
        finally:
            pdf_doc.close()

    @staticmethod
    def _build_image_url(
        kb_id: str,
        doc_id: str,
        image_path: str | None,
        stored_path: str,
    ) -> str | None:
        """将存储路径转为前端可访问的图片 URL。"""
        from src.services.kb_utils import build_image_url

        return build_image_url(kb_id, doc_id, image_path, stored_path)
