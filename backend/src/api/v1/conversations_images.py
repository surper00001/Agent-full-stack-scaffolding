"""对话图片上传与 VLM 描述 — 从 conversations.py 提取的独立路由。"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from loguru import logger

from src.api.deps import CurrentUser, get_current_user

router = APIRouter(prefix="/{conversation_id}", tags=["conversation-images"])

_CHAT_IMAGES_DIR = Path("./data/chat-images")
_CHAT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tiff", ".tif"}


def _require_non_admin(user: CurrentUser) -> None:
    """非管理员用户检查。"""
    if user.username == "admin_tt":
        # 管理员仅限管理操作，不允许参与对话
        from src.core.exceptions import ForbiddenError
        raise ForbiddenError("管理员账户不可参与对话")


@router.post("/images", summary="上传聊天图片（VLM 识别后作为上下文注入）")
async def upload_chat_image(
    conversation_id: str,
    file: UploadFile = File(..., description="图片文件"),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """上传图片到对话中，返回 image_id 供 send 接口使用。"""
    _require_non_admin(current_user)
    if not file.filename:
        return {"success": False, "code": 40001, "message": "文件名不能为空"}

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        return {
            "success": False,
            "code": 40002,
            "message": f"不支持的图片格式: {ext}，支持: {', '.join(_ALLOWED_IMAGE_EXTS)}",
        }

    mime_ext = ".jpg" if ext in (".jpg", ".jpeg") else ext

    image_id = uuid.uuid4().hex[:12]
    user_dir = _CHAT_IMAGES_DIR / current_user.id / conversation_id
    user_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{image_id}{mime_ext}"
    filepath = user_dir / filename

    try:
        contents = await file.read()
        filepath.write_bytes(contents)
        logger.info(f"聊天图片已保存: {filepath} ({len(contents)} bytes)")
    except Exception as e:
        logger.error(f"聊天图片保存失败: {e}")
        return {"success": False, "code": 50001, "message": f"图片保存失败: {e}"}

    # 立即用 VLM 预识别图片，以便前端可展示预览文本
    vlm_preview: str | None = None
    try:
        from src.services.vlm_service import get_vlm_service
        vlm = get_vlm_service()
        if vlm.enabled:
            vlm_preview, _ = vlm.describe_image(contents, mime_ext.lstrip("."))
            if vlm_preview:
                vlm_preview = vlm_preview.strip()
    except Exception as e:
        logger.debug(f"VLM 图片预览失败: {e}")

    return {
        "success": True,
        "code": 200,
        "data": {
            "image_id": image_id,
            "filename": file.filename,
            "preview": vlm_preview,
        },
    }


async def resolve_image_descriptions(
    image_ids: list[str], user_id: str, conversation_id: str
) -> str:
    """根据 image_ids 读取本地图片并调用 VLM 生成描述文本。

    Returns:
        拼接后的图片描述文本，可直接注入到用户消息中。
    """
    from src.services.vlm_service import get_vlm_service

    vlm = get_vlm_service()
    if not vlm.enabled:
        return ""

    parts: list[str] = []
    user_dir = _CHAT_IMAGES_DIR / user_id / conversation_id

    for iid in image_ids:
        # 安全检查：image_id 仅允许 hex 字符
        if not iid or len(iid) > 20 or not all(c in "0123456789abcdef" for c in iid):
            continue
        # 查找匹配的文件
        matched = None
        if user_dir.exists():
            for f in user_dir.iterdir():
                if f.stem == iid:
                    matched = f
                    break
        if not matched:
            continue
        try:
            img_bytes = matched.read_bytes()
            ext = matched.suffix.lstrip(".")
            desc, err = vlm.describe_image(img_bytes, ext)
            if desc and desc.strip():
                parts.append(f"[图片 {iid}]: {desc.strip()}")
                logger.info(f"VLM 图片描述 ({iid}): {desc[:80]}...")
            elif err:
                logger.warning(f"VLM 图片描述失败 ({iid}): {err}")
        except Exception as e:
            logger.error(f"读取图片失败 ({iid}): {e}")

    if parts:
        return "\n\n".join(parts)
    return ""
