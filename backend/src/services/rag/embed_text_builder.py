"""
Metadata-aware embedding 文本构造器。

不是嵌入纯文本，而是嵌入结构化字段的组合：
[文档] [文档类型] [语义标签] [章节路径] [标题] [摘要] [关联表格] [关联图片] {content}

每个字段都是独立的语义维度，帮助向量模型按文档名/类型/章节/标题/关联元素召回。

从 KnowledgeBaseService 中独立出来，便于单测和扩展。
"""

from __future__ import annotations

from typing import Any

# ── 嵌入文本长度上限 ──────────────────────────────────────
# Qwen3-Embedding 最大序列长度 32768 tokens
# 中文字符 ≈ 1-2 tokens/char，8192 字符 ≈ 8192-16384 tokens，安全
EMBED_TEXT_MAX_CHARS = 8192


# ── 文档类型中文标签 ──────────────────────────────────────

DOC_CATEGORY_LABELS: dict[str, str] = {
    "academic": "学术论文",
    "technical": "技术文档",
    "legal": "法律/合同",
    "report": "报告/白皮书",
    "markdown": "Markdown 技术文档",
    "general": "通用文档",
}


# ── 版面语义标签中文映射 ──────────────────────────────────

LAYOUT_TAG_LABELS: dict[str, str] = {
    "title": "文档标题",
    "heading": "章节标题",
    "subtitle": "副标题",
    "body": "正文",
    "abstract": "摘要",
    "keywords": "关键词",
    "caption": "图表说明",
    "header": "页眉",
    "footer": "页脚",
    "footnote": "脚注",
    "reference": "参考文献",
    "list_item": "列表项",
    "table_body": "表格",
    "image_region": "图片区域",
    "code": "代码块",
}


# ── 公开 API ──────────────────────────────────────────────


def build_embed_text(
    chunk: Any,
    doc_filename: str = "",
    refs_captions: dict[str, str] | None = None,
) -> str:
    """构建 metadata-aware embedding 输入。

    结构化前缀帮助向量模型按文档名/类型/章节/语义标签/关联图表召回，
    比纯文本 embedding 准确度显著提升。
    """
    parts: list[str] = []

    # 源文档 —— 核心召回信号，支持按文档名搜索
    if doc_filename:
        parts.append(f"[文档] {doc_filename}")

    # 文档类型 —— 学术论文/技术文档/法律合同等
    doc_cat = getattr(chunk, "doc_category", None) or ""
    cat_label = DOC_CATEGORY_LABELS.get(doc_cat, "")
    if cat_label:
        parts.append(f"[文档类型] {cat_label}")

    # 版面语义标签 —— 标题/正文/表格/图片等
    layout_tag = getattr(chunk, "layout_tag", None) or ""
    tag_label = LAYOUT_TAG_LABELS.get(layout_tag, "")
    if tag_label:
        parts.append(f"[语义标签] {tag_label}")

    # 章节层级路径 —— 核心召回信号
    if chunk.section_path:
        parts.append(f"[章节路径] {chunk.section_path}")
    elif chunk.section_title:
        parts.append(f"[章节] {chunk.section_title}")

    # 标题 —— chunk 归属的具体章节标题（如 "3.2 数字孪生系统"）
    title = getattr(chunk, "title", None) or chunk.section_title
    if title and chunk.section_path and title != chunk.section_path:
        parts.append(f"[标题] {title}")

    # 关联表格/图片 —— 帮助 embedding 理解文本块关联的可视化元素
    table_refs = getattr(chunk, "table_refs", None) or []
    image_refs = getattr(chunk, "image_refs", None) or []
    if table_refs and refs_captions:
        captions = [refs_captions.get(tid, "") for tid in table_refs]
        captions = [c for c in captions if c]
        if captions:
            parts.append(f"[关联表格] {' | '.join(captions)}")
    if image_refs and refs_captions:
        captions = [refs_captions.get(iid, "") for iid in image_refs]
        captions = [c for c in captions if c]
        if captions:
            parts.append(f"[关联图片] {' | '.join(captions)}")

    # 内容摘要 —— 粗粒度语义信号
    if chunk.content_summary:
        parts.append(f"[摘要] {chunk.content_summary}")

    # 正文
    parts.append(chunk.content)

    full = "\n".join(parts)
    if len(full) > EMBED_TEXT_MAX_CHARS:
        from loguru import logger
        logger.warning(
            f"embedding 文本超长已截断: chunk={getattr(chunk, 'chunk_id', '?')} "
            f"len={len(full)} max={EMBED_TEXT_MAX_CHARS}"
        )
        return truncate_embed_text(full, EMBED_TEXT_MAX_CHARS)
    return full


def truncate_embed_text(text: str, max_chars: int = EMBED_TEXT_MAX_CHARS) -> str:
    """智能截断：metadata 前缀全部保留，仅截断正文尾部。

    策略：
    1. 找到最后一个 metadata 标签的位置作为"元数据区"边界
    2. 元数据区完整保留，正文在标点处截断
    3. 无元数据时走简单 fallback
    """
    if len(text) <= max_chars:
        return text

    # ── 找到正文起始位置（最后一个 metadata 标签之后）──
    meta_end = 0
    for marker in (
        "[摘要] ", "[关联图片] ", "[关联表格] ", "[标题] ",
        "[章节] ", "[章节路径] ", "[语义标签] ", "[文档类型] ", "[文档] ",
    ):
        idx = text.rfind(marker)
        if idx > meta_end:
            # 找到该 marker 值的结束位置（下一个 [ 标签或换行）
            end = text.find("\n[", idx + len(marker))
            if end == -1:
                end = text.find("\n", idx + len(marker))
            if end > meta_end:
                meta_end = end

    # ── 元数据区完整保留，仅截断正文 ──
    if meta_end > 0 and meta_end < max_chars // 2:
        header = text[:meta_end + 1]
        body_budget = max_chars - len(header) - 6  # 预留 "\n" + "..."
        if body_budget < 100:
            body_budget = 100
        body = text[meta_end + 1:]
        truncated_body = body[:body_budget]
        for punct in ("\n\n", "。", ". ", "！", "？", "\n", " "):
            idx = truncated_body.rfind(punct)
            if idx > body_budget // 2:
                return header + "\n" + truncated_body[: idx + len(punct)] + "..."
        return header + "\n" + truncated_body + "..."

    # ── 简单 fallback：无元数据标签时在标点处截断 ──
    truncated = text[:max_chars - 3]  # 预留 "..." 空间
    for punct in ("\n\n", "。", "！", "？", ". ", "\n", " "):
        idx = truncated.rfind(punct)
        if idx > (max_chars - 3) // 2:
            return truncated[: idx + len(punct)] + "..."
    return truncated + "..."
