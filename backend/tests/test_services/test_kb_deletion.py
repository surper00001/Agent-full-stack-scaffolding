"""知识库级联删除单元测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.domain.knowledge_base import KBChunk, KBDocument, KnowledgeBase
from src.services.knowledge_base_service import KnowledgeBaseService


def _make_service() -> KnowledgeBaseService:
    session = MagicMock()
    svc = KnowledgeBaseService(session)
    svc._vector_store = AsyncMock()
    svc._file_storage = MagicMock()
    svc._chunk_repo = AsyncMock()
    svc._doc_repo = AsyncMock()
    svc._kb_repo = AsyncMock()
    svc._progress = MagicMock()
    return svc


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_document_cascades_vectors_files_and_chunks() -> None:
    svc = _make_service()
    tenant_id = "default"
    kb_id = "kb-1"
    doc_id = "doc-1"
    user_id = "user-1"

    doc = MagicMock(spec=KBDocument)
    doc.id = doc_id
    doc.stored_path = "default/user-1/kb-1/files/doc-1.pdf"
    doc.chunk_count = 3
    doc.file_size = 1024

    kb = MagicMock(spec=KnowledgeBase)
    kb.id = kb_id
    kb.user_id = user_id
    kb.document_count = 1
    kb.total_chunks = 3
    kb.total_size_bytes = 1024

    chunk = MagicMock(spec=KBChunk)
    chunk.vector_id = "vec-1"

    svc.get_document = AsyncMock(return_value=doc)
    svc.get_kb = AsyncMock(return_value=kb)
    svc._chunk_repo.list_all = AsyncMock(return_value=[chunk])
    async def track_chunks(**_k: object) -> int:
        call_order.append("chunks")
        return 3

    svc._chunk_repo.hard_delete_by_filter = AsyncMock(side_effect=track_chunks)
    svc._kb_repo.update = AsyncMock(return_value=kb)
    svc._doc_repo.soft_delete = AsyncMock(return_value=True)

    call_order: list[str] = []

    async def track_vectors(*_a: object, **_k: object) -> bool:
        call_order.append("vectors_ids")
        return True

    async def track_filter(*_a: object, **_k: object) -> bool:
        call_order.append("vectors_filter")
        return True

    svc._vector_store.delete_by_ids = AsyncMock(side_effect=track_vectors)
    svc._vector_store.delete_by_filter = AsyncMock(side_effect=track_filter)

    async def run_sync(fn: object, *args: object, **kwargs: object) -> None:
        assert fn == svc._file_storage.delete_document_assets
        call_order.append("files")
        fn(*args, **kwargs)  # type: ignore[operator]

    with patch(
        "src.services.knowledge_base_service.asyncio.to_thread",
        side_effect=run_sync,
    ):
        await svc.delete_document(doc_id, kb_id, tenant_id, user_id)

    assert call_order.index("vectors_ids") < call_order.index("vectors_filter")
    assert call_order.index("vectors_filter") < call_order.index("files")
    assert call_order.index("files") < call_order.index("chunks")

    svc._vector_store.delete_by_ids.assert_awaited()
    svc._vector_store.delete_by_filter.assert_awaited_once_with(
        {"document_id": doc_id},
        f"kb_{kb_id}",
        tenant_id,
    )
    svc._file_storage.delete_document_assets.assert_called_once_with(
        tenant_id, user_id, kb_id, doc_id, doc.stored_path
    )
    svc._chunk_repo.hard_delete_by_filter.assert_awaited_once_with(
        tenant_id=tenant_id, document_id=doc_id
    )
    svc._doc_repo.soft_delete.assert_awaited_once_with(doc_id)
    svc._progress.cleanup.assert_called_once_with(doc_id)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_kb_collection_files_and_db() -> None:
    svc = _make_service()
    tenant_id = "default"
    kb_id = "kb-1"
    user_id = "user-1"

    kb = MagicMock(spec=KnowledgeBase)
    kb.id = kb_id

    doc = MagicMock(spec=KBDocument)
    doc.id = "doc-1"

    svc.get_kb = AsyncMock(return_value=kb)
    svc._doc_repo.list_all = AsyncMock(return_value=[doc])
    svc._chunk_repo.soft_delete_by_filter = AsyncMock(return_value=5)
    svc._doc_repo.soft_delete_by_filter = AsyncMock(return_value=1)
    svc._kb_repo.soft_delete = AsyncMock(return_value=True)
    svc._vector_store.delete_collection = AsyncMock(return_value=True)

    async def run_sync(fn: object, *args: object, **kwargs: object) -> None:
        assert fn == svc._file_storage.delete_kb_files
        fn(*args, **kwargs)  # type: ignore[operator]

    with patch(
        "src.services.knowledge_base_service.asyncio.to_thread",
        side_effect=run_sync,
    ):
        await svc.delete_kb(kb_id, tenant_id, user_id)

    svc._vector_store.delete_collection.assert_awaited_once_with(
        f"kb_{kb_id}", tenant_id
    )
    svc._vector_store.delete_by_ids.assert_not_awaited()
    svc._file_storage.delete_kb_files.assert_called_once_with(
        tenant_id, user_id, kb_id
    )
    svc._chunk_repo.soft_delete_by_filter.assert_awaited_once_with(
        tenant_id=tenant_id, knowledge_base_id=kb_id
    )
    svc._doc_repo.soft_delete_by_filter.assert_awaited_once_with(
        tenant_id=tenant_id, knowledge_base_id=kb_id
    )
    svc._kb_repo.soft_delete.assert_awaited_once_with(kb_id)
    svc._progress.cleanup.assert_called_once_with(doc.id)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_delete_kb_fallback_per_doc_vectors_when_collection_fails() -> None:
    svc = _make_service()
    tenant_id = "default"
    kb_id = "kb-1"
    user_id = "user-1"

    kb = MagicMock(spec=KnowledgeBase)
    kb.id = kb_id
    doc = MagicMock(spec=KBDocument)
    doc.id = "doc-1"

    svc.get_kb = AsyncMock(return_value=kb)
    svc._doc_repo.list_all = AsyncMock(return_value=[doc])
    svc._purge_document_vectors = AsyncMock()
    svc._chunk_repo.soft_delete_by_filter = AsyncMock(return_value=0)
    svc._doc_repo.soft_delete_by_filter = AsyncMock(return_value=0)
    svc._kb_repo.soft_delete = AsyncMock(return_value=True)
    svc._vector_store.delete_collection = AsyncMock(
        side_effect=RuntimeError("collection missing")
    )

    async def run_sync(fn: object, *args: object, **kwargs: object) -> None:
        fn(*args, **kwargs)  # type: ignore[operator]

    with patch(
        "src.services.knowledge_base_service.asyncio.to_thread",
        side_effect=run_sync,
    ):
        await svc.delete_kb(kb_id, tenant_id, user_id)

    svc._purge_document_vectors.assert_awaited_once_with(
        doc.id, kb_id, tenant_id
    )
