"""
API 路由聚合模块。

将所有子路由注册到主路由上，统一管理版本化 API。
"""

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse
from loguru import logger

from src.api.v1 import agents, auth, conversations, health, knowledge_base, tenant
from src.core.config import get_settings

# 创建 v1 版本路由
api_v1_router = APIRouter(prefix="/api/v1")
api_v1_router.include_router(health.router)
api_v1_router.include_router(auth.router)
api_v1_router.include_router(agents.router)
api_v1_router.include_router(conversations.router)
api_v1_router.include_router(tenant.router)
api_v1_router.include_router(knowledge_base.router)

# 文件下载路由（Agent 生成文件）
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
