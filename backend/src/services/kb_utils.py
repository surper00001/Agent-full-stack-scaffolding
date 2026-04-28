"""知识库共享工具函数。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_image_url(
    kb_id: str,
    doc_id: str,
    image_path: str | None,
    stored_path: str,
) -> str | None:
    """将存储路径转为前端可访问的图片 URL。"""
    if not image_path:
        return None
    if image_path == stored_path:
        return f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/download"
    image_name = Path(image_path).name
    if not image_name:
        return None
    return f"/api/v1/knowledge-bases/{kb_id}/documents/{doc_id}/images/{image_name}"


def build_rerank_text(metadata: dict[str, Any], page_content: str) -> str:
    """与索引 embedding 对齐的 rerank 输入文本。"""
    parts: list[str] = []
    if metadata.get("section_path"):
        parts.append(f"章节: {metadata['section_path']}")
    if metadata.get("section_title"):
        parts.append(f"标题: {metadata['section_title']}")
    if metadata.get("content_summary"):
        parts.append(f"摘要: {metadata['content_summary']}")
    parts.append(page_content)
    return "\n".join(parts)
