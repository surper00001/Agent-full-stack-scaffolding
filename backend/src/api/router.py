"""
API 路由聚合模块。

将所有子路由注册到主路由上，统一管理版本化 API。
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from loguru import logger

from src.api.v1 import admin as admin_stats
from src.api.v1 import (
    agents,
    auth,
    conversations,
    conversations_search,
    health,
    knowledge_base,
    observability,
    skills,
    tenant,
    users,
)
from src.core.config import get_settings

# 创建 v1 版本路由
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(agents.router)
api_v1_router.include_router(conversations.router)
api_v1_router.include_router(conversations_search.router)
api_v1_router.include_router(tenant.router)
api_v1_router.include_router(admin_stats.router)
api_v1_router.include_router(users.router)
api_v1_router.include_router(knowledge_base.router)
api_v1_router.include_router(skills.router)
api_v1_router.include_router(observability.router)

# 文件下载路由（Agent 生成文件）
# 思维导图导出文件（子目录）
@api_v1_router.get("/files/mindmap_exports/{filename}", summary="下载导出的思维导图文件", tags=["文件"])
async def download_mindmap_export(filename: str) -> FileResponse:
    """下载 MindMap 导出文件（OPML / FreeMind / Markdown / JSON）。"""
    settings = get_settings()
    export_dir = Path(settings.file_output_dir) / "mindmap_exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    file_path = (export_dir / filename).resolve()
    allowed_base = export_dir.resolve()

    if not str(file_path).startswith(str(allowed_base)):
        logger.warning(f"文件下载路径穿越尝试: {filename}")
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="禁止访问")

    if not file_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    suffix_map = {
        ".opml": "text/xml; charset=utf-8",
        ".mm": "text/xml; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".json": "application/json; charset=utf-8",
    }
    media_type = suffix_map.get(file_path.suffix, "application/octet-stream")
    return FileResponse(
        path=str(file_path),
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_v1_router.get("/files/{filename}", summary="下载 Agent 生成的文件", tags=["文件"])
async def download_file(filename: str) -> FileResponse:
    """下载 Agent 生成的 Markdown/TXT/SRT 等文件。"""
    settings = get_settings()
    file_path = Path(settings.file_output_dir) / filename

    # 安全检查：防止路径穿越
    resolved = file_path.resolve()
    allowed_base = Path(settings.file_output_dir).resolve()
    if not str(resolved).startswith(str(allowed_base)):
        logger.warning(f"文件下载路径穿越尝试: {filename}")
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="禁止访问")

    if not resolved.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="文件不存在或已过期")

    suffix_map = {
        ".md": "text/markdown; charset=utf-8",
        ".txt": "text/plain; charset=utf-8",
        ".srt": "text/plain; charset=utf-8",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    media_type = suffix_map.get(resolved.suffix, "application/octet-stream")

    return FileResponse(
        path=str(resolved),
        media_type=media_type,
        filename=filename,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

# 根路由
root_router = APIRouter()
root_router.include_router(api_v1_router)
