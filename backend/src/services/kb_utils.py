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
    """构建与索引 embedding 对齐的 rerank 输入文本。

    与 KnowledgeBaseService._build_embed_text() 保持相同的结构化字段顺序，
    确保 reranker 评分与 embedding 相似度一致。
    """
    parts: list[str] = []

    # 文档名
    if metadata.get("document_filename"):
        parts.append(f"[文档] {metadata['document_filename']}")

    # 文档类型
    doc_cat = metadata.get("doc_category", "")
    _DOC_CATEGORY_LABELS = {
        "academic": "学术论文", "technical": "技术文档", "legal": "法律/合同",
        "report": "报告/白皮书", "markdown": "Markdown 技术文档", "general": "通用文档",
    }
    if doc_cat and doc_cat in _DOC_CATEGORY_LABELS:
        parts.append(f"[文档类型] {_DOC_CATEGORY_LABELS[doc_cat]}")

    # 版面语义标签
    layout_tag = metadata.get("layout_tag", "")
    _LAYOUT_TAG_LABELS = {
        "title": "文档标题", "heading": "章节标题", "subtitle": "副标题",
        "body": "正文", "abstract": "摘要", "keywords": "关键词",
        "caption": "图表说明", "header": "页眉", "footer": "页脚",
        "footnote": "脚注", "reference": "参考文献", "list_item": "列表项",
        "table_body": "表格", "image_region": "图片区域", "code": "代码块",
    }
    if layout_tag and layout_tag in _LAYOUT_TAG_LABELS:
        parts.append(f"[语义标签] {_LAYOUT_TAG_LABELS[layout_tag]}")

    # 章节路径
    if metadata.get("section_path"):
        parts.append(f"[章节路径] {metadata['section_path']}")
    elif metadata.get("section_title"):
        parts.append(f"[章节] {metadata['section_title']}")

    # 标题
    title = metadata.get("title") or metadata.get("section_title", "")
    if title and metadata.get("section_path") and title != metadata.get("section_path", ""):
        parts.append(f"[标题] {title}")

    # 关联表格/图片
    table_refs = metadata.get("table_refs") or []
    image_refs = metadata.get("image_refs") or []
    if table_refs:
        parts.append(f"[关联表格] {len(table_refs)} 个")
    if image_refs:
        parts.append(f"[关联图片] {len(image_refs)} 个")

    # 摘要
    if metadata.get("content_summary"):
        parts.append(f"[摘要] {metadata['content_summary']}")

    parts.append(page_content)
    return "\n".join(parts)
