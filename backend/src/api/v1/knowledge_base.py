"""
知识库 API 路由。

提供知识库 CRUD、文档上传/管理、检索、文档查看、源文件下载。
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_tenant, get_current_user
from src.core.config import get_settings
from src.core.exceptions import ValidationError
from src.db.session import get_db_session
from src.models.schemas.knowledge_base import (
    KBDocumentListItem,
    KBDocumentResponse,
    KBDocumentViewResponse,
    KBProcessProgressResponse,
    KBSearchRequest,
    KBSearchResponse,
    KBUploadResponse,
    KnowledgeBaseListItem,
    KnowledgeBaseResponse,
)
from src.models.schemas.response import APIResponse, PaginatedData
from src.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


def _kb_service(db: AsyncSession) -> KnowledgeBaseService:
    return KnowledgeBaseService(db)


# ==================== 知识库 CRUD ====================


@router.post("", summary="创建知识库")
async def create_knowledge_base(
    name: str = Query(min_length=1, max_length=255),
    description: str | None = Query(default=None, max_length=2000),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KnowledgeBaseResponse]:
    svc = _kb_service(db)
    kb = await svc.create_kb(
        name=name,
        user_id=current_user.id,
        tenant_id=tenant_id,
        description=description,
    )
    return APIResponse(message="知识库创建成功", data=KnowledgeBaseResponse.model_validate(kb))


@router.get("", summary="获取知识库列表")
async def list_knowledge_bases(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[KnowledgeBaseListItem]]:
    svc = _kb_service(db)
    skip = (page - 1) * page_size
    kbs = await svc.list_kbs(current_user.id, tenant_id, skip=skip, limit=page_size)
    total = await svc.count_kbs(current_user.id, tenant_id)
    items = [KnowledgeBaseListItem.model_validate(k) for k in kbs]
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return APIResponse(
        data=PaginatedData(items=items, total=total, page=page, page_size=page_size, pages=pages)
    )


@router.get("/{kb_id}", summary="获取知识库详情")
async def get_knowledge_base(
    kb_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KnowledgeBaseResponse]:
    svc = _kb_service(db)
    settings = get_settings()
    kb = await svc.get_kb(kb_id, tenant_id)
    index_status = await svc.check_index_status(kb_id, tenant_id)
    data = KnowledgeBaseResponse.model_validate(kb)
    data.indexed_model = index_status.get("indexed_model")
    data.needs_reindex = index_status.get("needs_reindex", False)
    data.server_embedding_model = settings.kb_embedding_model
    data.server_reranker_model = settings.kb_reranker_model
    data.models_differ_from_env = (
        kb.embedding_model != settings.kb_embedding_model
        or kb.reranker_model != settings.kb_reranker_model
    )
    return APIResponse(data=data)


@router.put("/{kb_id}", summary="更新知识库")
async def update_knowledge_base(
    kb_id: str,
    name: str | None = Query(default=None, min_length=1, max_length=255),
    description: str | None = Query(default=None, max_length=2000),
    chunk_size: int | None = Query(default=None, ge=100, le=4000),
    chunk_overlap: int | None = Query(default=None, ge=0, le=500),
    embedding_model: str | None = Query(default=None, max_length=255),
    reranker_model: str | None = Query(default=None, max_length=255),
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KnowledgeBaseResponse]:
    svc = _kb_service(db)
    kb = await svc.update_kb(
        kb_id, tenant_id,
        name=name, description=description,
        chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        embedding_model=embedding_model, reranker_model=reranker_model,
    )
    return APIResponse(message="更新成功", data=KnowledgeBaseResponse.model_validate(kb))


@router.delete("/{kb_id}", summary="删除知识库")
async def delete_knowledge_base(
    kb_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[None]:
    svc = _kb_service(db)
    await svc.delete_kb(kb_id, tenant_id, current_user.id)
    return APIResponse(message="知识库已删除")


# ==================== 文档管理 ====================


@router.post("/{kb_id}/documents", summary="上传文档")
async def upload_document(
    kb_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KBUploadResponse]:
    if not file.filename:
        raise ValidationError("文件名不能为空")

    content = await file.read()
    svc = _kb_service(db)

    doc = await svc.upload_document(
        kb_id=kb_id,
        filename=file.filename,
        file_content=content,
        tenant_id=tenant_id,
        user_id=current_user.id,
    )

    # 确保文档记录已持久化，后台任务在新 session 中才能读到
    await db.commit()

    background_tasks.add_task(
        _process_document_background,
        doc_id=doc.id,
        kb_id=kb_id,
        tenant_id=tenant_id,
        _user_id=current_user.id,
    )

    return APIResponse(
        message="文档已上传，正在后台处理",
        data=KBUploadResponse(
            document_id=doc.id,
            filename=doc.filename,
            file_size=doc.file_size,
            file_type=doc.file_type,
            status=doc.status,
            message="文档已上传，后台处理中",
        ),
    )


async def _process_document_background(
    doc_id: str, kb_id: str, tenant_id: str, _user_id: str
) -> None:
    """后台处理文档任务（独立 session）。"""
    import traceback

    from loguru import logger

    from src.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        svc = KnowledgeBaseService(session)
        try:
            await svc.process_document(doc_id, kb_id, tenant_id, _user_id)
            await session.commit()
            logger.info(f"后台文档处理成功: {doc_id}")
        except Exception:
            await session.rollback()
            logger.error(f"后台文档处理失败:\n{traceback.format_exc()}")


@router.get("/{kb_id}/documents", summary="获取文档列表")
async def list_documents(
    kb_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[KBDocumentListItem]]:
    svc = _kb_service(db)
    await svc.get_kb(kb_id, tenant_id)
    skip = (page - 1) * page_size
    docs = await svc.list_documents(kb_id, tenant_id, skip=skip, limit=page_size)
    total = await svc.count_documents(kb_id, tenant_id)
    items = [KBDocumentListItem.model_validate(d) for d in docs]
    pages = (total + page_size - 1) // page_size if total > 0 else 0
    return APIResponse(
        data=PaginatedData(items=items, total=total, page=page, page_size=page_size, pages=pages)
    )


@router.get("/{kb_id}/documents/{doc_id}", summary="获取文档详情")
async def get_document(
    doc_id: str,
    kb_id: str,  # noqa: ARG001
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KBDocumentResponse]:
    svc = _kb_service(db)
    doc = await svc.get_document(doc_id, tenant_id)
    return APIResponse(data=KBDocumentResponse.model_validate(doc))


@router.get(
    "/{kb_id}/documents/{doc_id}/progress",
    summary="查询文档处理进度",
)
async def get_document_progress(
    doc_id: str,
    kb_id: str,  # noqa: ARG001
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KBProcessProgressResponse | None]:
    svc = _kb_service(db)
    # 先确认文档存在
    await svc.get_document(doc_id, tenant_id)
    progress = svc.get_document_progress(doc_id)
    return APIResponse(data=KBProcessProgressResponse(**progress) if progress else None)


@router.post("/{kb_id}/documents/{doc_id}/reprocess", summary="重新处理文档")
async def reprocess_document(
    kb_id: str,
    doc_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    svc = _kb_service(db)
    await svc.prepare_reprocess(doc_id, kb_id, tenant_id)
    await db.commit()

    background_tasks.add_task(
        _process_document_background,
        doc_id=doc_id,
        kb_id=kb_id,
        tenant_id=tenant_id,
        _user_id=current_user.id,
    )
    return APIResponse(message="已提交重新处理", data={"document_id": doc_id})


@router.delete("/{kb_id}/documents/{doc_id}", summary="删除文档")
async def delete_document(
    kb_id: str,
    doc_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[None]:
    svc = _kb_service(db)
    await svc.delete_document(doc_id, kb_id, tenant_id, current_user.id)
    return APIResponse(message="文档已删除")


# ==================== 检索 ====================


# index-status / reindex 放在 documents 路由之前，避免旧版 Starlette 路径歧义
@router.get("/{kb_id}/index-status", summary="检查索引模型一致性")
async def get_index_status(
    kb_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    svc = _kb_service(db)
    status = await svc.check_index_status(kb_id, tenant_id)
    return APIResponse(data=status)


@router.post("/{kb_id}/reindex", summary="重建知识库向量索引")
async def reindex_knowledge_base(
    kb_id: str,
    background_tasks: BackgroundTasks,
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[dict]:
    from loguru import logger

    async def _run() -> None:
        from src.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            inner = KnowledgeBaseService(session)
            try:
                result = await inner.reindex_kb(kb_id, tenant_id)
                await session.commit()
                logger.info(f"重建索引完成: {result}")
            except Exception:
                await session.rollback()
                raise

    background_tasks.add_task(_run)
    return APIResponse(message="重建索引任务已启动，请稍后刷新查看", data={"kb_id": kb_id})


@router.post("/{kb_id}/search", summary="搜索知识库")
async def search_knowledge_base(
    kb_id: str,
    body: KBSearchRequest,
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KBSearchResponse]:
    svc = _kb_service(db)
    result = await svc.search(
        kb_id=kb_id,
        query=body.query,
        tenant_id=tenant_id,
        top_k=body.top_k,
        rerank=body.rerank,
        filters=body.filters,
    )
    return APIResponse(data=KBSearchResponse(**result))


# ==================== 文档查看 ====================


@router.get("/{kb_id}/documents/{doc_id}/view", summary="查看文档（按页）")
async def view_document(
    doc_id: str,
    kb_id: str,  # noqa: ARG001
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[KBDocumentViewResponse]:
    svc = _kb_service(db)
    result = await svc.view_document(doc_id, tenant_id)
    return APIResponse(data=KBDocumentViewResponse(**result))


@router.get("/{kb_id}/documents/{doc_id}/download", summary="下载源文件")
async def download_source_file(
    doc_id: str,
    kb_id: str,  # noqa: ARG001
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """下载存档的源文件。"""
    from fastapi.responses import Response

    svc = _kb_service(db)
    content, filename = await svc.download_source_file(doc_id, tenant_id)

    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    mime_map: dict[str, str] = {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "doc": "application/msword",
        "txt": "text/plain",
        "md": "text/markdown",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
        },
    )


@router.get("/{kb_id}/documents/{doc_id}/images/{image_name}", summary="获取文档内嵌图片")
async def get_document_image(
    doc_id: str,
    kb_id: str,  # noqa: ARG001
    image_name: str,
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """返回 PDF/Word 解析时提取并存档的内嵌图片。"""
    from fastapi.responses import Response

    svc = _kb_service(db)
    content, ext = await svc.get_document_image(doc_id, tenant_id, image_name)

    mime_map = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "bmp": "image/bmp",
        "webp": "image/webp",
        "tif": "image/tiff",
        "tiff": "image/tiff",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Length": str(len(content))},
    )


@router.get(
    "/{kb_id}/documents/{doc_id}/pages/{page_num}/preview",
    summary="PDF 页面预览",
)
async def preview_document_page(
    doc_id: str,
    kb_id: str,  # noqa: ARG001
    page_num: int,
    scale: float = 2.0,
    tenant_id: str = Depends(get_current_tenant),
    _current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """渲染 PDF 指定页为 PNG，响应头附带页面尺寸。"""
    from fastapi.responses import Response

    svc = _kb_service(db)
    content, page_width, page_height = await svc.render_page_preview(
        doc_id, tenant_id, page_num, scale
    )

    return Response(
        content=content,
        media_type="image/png",
        headers={
            "Content-Length": str(len(content)),
            "X-Page-Width": str(page_width),
            "X-Page-Height": str(page_height),
        },
    )
