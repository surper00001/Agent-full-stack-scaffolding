"""
RAG 上下文构建器 —— 统一检索结果格式化，供聊天预检索与 Agent 工具复用。

支持全部 chunk 类型：
- text      → [来源N] 纯文本引用
- table     → [表格:N] 表格内联渲染
- image     → [图片:N] 图片内联渲染
- code      → [代码:N] 代码块内联渲染
- formula   → [来源N] 公式文本引用
- reference → [来源N] 参考文献引用
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from src.services.knowledge_base_service import KnowledgeBaseService


@dataclass
class CitationItem:
    """单条引用来源——metadata-aware 结构化引用，支持全部 chunk 类型。"""

    chunk_id: str
    content: str
    source: str
    page: int
    score: float
    chunk_type: str = "text"
    section_title: str = ""
    title: str = ""  # chunk 归属的章节标题
    document_id: str | None = None
    # 表格字段
    table_html: str = ""
    table_caption: str = ""
    # 图片字段
    image_url: str = ""
    image_description: str = ""
    image_caption: str = ""
    ocr_status: str = ""
    image_width: int | None = None
    image_height: int | None = None


@dataclass
class RAGContext:
    """检索上下文结果。"""

    query: str
    kb_id: str
    kb_name: str
    citations: list[CitationItem] = field(default_factory=list)
    context_text: str = ""
    total_found: int = 0
    returned: int = 0
    low_confidence: bool = False
    suggestion: str = ""

    def to_metadata(self, rag_mode: str = "proactive") -> dict[str, Any]:
        return {
            "citations": [
                {
                    "chunk_id": c.chunk_id,
                    "content": c.content,
                    "source": c.source,
                    "page": c.page,
                    "score": c.score,
                    "chunk_type": c.chunk_type,
                    "section_title": c.section_title,
                    "title": c.title,
                    "document_id": c.document_id,
                    "table_html": c.table_html,
                    "table_caption": c.table_caption,
                    "image_url": c.image_url,
                    "image_description": c.image_description,
                    "image_caption": c.image_caption,
                    "ocr_status": c.ocr_status,
                    "image_width": c.image_width,
                    "image_height": c.image_height,
                }
                for c in self.citations
            ],
            "rag_mode": rag_mode,
            "kb_id": self.kb_id,
        }

    def to_tool_json(self) -> str:
        """与 search_knowledge_base 工具返回格式一致。"""
        return json.dumps(
            {
                "query": self.query,
                "total_found": self.total_found,
                "returned": self.returned,
                "results": [
                    {
                        "content": c.content,
                        "source": c.source,
                        "page": c.page,
                        "score": c.score,
                        "chunk_id": c.chunk_id,
                        "chunk_type": c.chunk_type,
                        "section_title": c.section_title,
                        "title": c.title,
                        "table_html": c.table_html,
                        "table_caption": c.table_caption,
                        "image_url": c.image_url,
                        "image_description": c.image_description,
                        "image_caption": c.image_caption,
                        "ocr_status": c.ocr_status,
                        "image_width": c.image_width,
                        "image_height": c.image_height,
                    }
                    for c in self.citations
                ],
                "context_for_llm": self.context_text,
            },
            ensure_ascii=False,
            indent=2,
        )


def _item_to_citation(item: dict[str, Any]) -> CitationItem:
    meta = item.get("metadata_") or {}
    meta = meta if isinstance(meta, dict) else {}
    img_w = meta.get("image_width")
    img_h = meta.get("image_height")
    return CitationItem(
        chunk_id=item.get("chunk_id", ""),
        content=item.get("expanded_content") or item.get("content", ""),
        source=item.get("document_filename", "未知"),
        page=item.get("page_start", 1),
        score=float(item.get("score", 0)),
        chunk_type=item.get("chunk_type", "text"),
        section_title=meta.get("section_title", ""),
        title=meta.get("title") or meta.get("section_title", ""),
        document_id=item.get("document_id"),
        table_html=meta.get("table_html", ""),
        table_caption=meta.get("table_caption", ""),
        image_url=meta.get("image_url", ""),
        image_description=meta.get("image_description", ""),
        image_caption=meta.get("image_caption", ""),
        ocr_status=meta.get("ocr_status", ""),
        image_width=int(img_w) if img_w is not None else None,
        image_height=int(img_h) if img_h is not None else None,
    )


def format_context_text(citations: list[CitationItem]) -> str:
    """将引用列表格式化为 LLM 可读的上下文文本。

    按 chunk 类型差异化处理：
    - text/formula/reference → 直接内容 + [来源N]
    - table                  → Markdown 表格 + HTML 源码 + [表格:N] 标记
    - image                  → VLM 描述 + OCR 文字 + [图片:N] 标记
    - code                   → 代码内容 + [代码:N] 标记
    """
    parts: list[str] = []
    for i, c in enumerate(citations):
        idx = i + 1
        source_info = f"[来源{idx}] {c.source}"
        if c.title:
            source_info += f" > {c.title}"
        elif c.section_title:
            source_info += f" > {c.section_title}"
        source_info += f" (第{c.page}页, 匹配度:{c.score:.0%})"

        if c.chunk_type == "table":
            # 表格：Markdown 版本 + HTML 源码（供 LLM 精确复制）+ 内联标记
            lines = [source_info]
            lines.append(f"[类型: 表格 | 表格引用标记: [表格:{idx}]]")
            if c.table_caption:
                lines.append(f"表格说明: {c.table_caption}")
            lines.append(f"表格内容 (Markdown):\n{c.content}")
            if c.table_html:
                # 截断过长的 HTML（表格通常不超 8000 字符）
                html = c.table_html[:8000]
                lines.append(f"表格 HTML 源码:\n{html}")
            parts.append("\n".join(lines))

        elif c.chunk_type == "image":
            # 图片：VLM 描述 + OCR 文字 + 内联标记
            lines = [source_info]
            lines.append(f"[类型: 图片 | 图片引用标记: [图片:{idx}]]")
            if c.image_description:
                lines.append(f"VLM 图片描述: {c.image_description}")
            if c.image_caption:
                lines.append(f"图片标题/标注: {c.image_caption}")
            if c.ocr_status == "success" and c.content.strip():
                lines.append(f"OCR 文字: {c.content.strip()}")
            if not c.image_description and not c.image_caption and not c.content.strip():
                lines.append("(此图片无可用的文字描述，请根据上下文推断内容)")
            parts.append("\n".join(lines))

        elif c.chunk_type == "code":
            # 代码块：保留代码内容 + 内联标记
            lines = [source_info]
            lines.append(f"[类型: 代码 | 代码引用标记: [代码:{idx}]]")
            lines.append(f"```\n{c.content}\n```")
            parts.append("\n".join(lines))

        else:
            # text / formula / reference：普通文本
            parts.append(f"{source_info}\n{c.content}")

    return "\n\n---\n\n".join(parts)


def build_system_rag_prompt(kb_name: str, context_text: str) -> str:
    """构建注入 system prompt 的 RAG 段落，支持图文/表格/代码混合回答。"""
    if not context_text.strip():
        return ""
    return (
        f"\n\n## 知识库检索结果（自动）\n"
        f"以下是从知识库「{kb_name}」检索到的相关内容，请优先基于这些信息回答，并标注来源。\n\n"
        f"**重要——混合内容引用规则：**\n"
        f"- 文本/公式/参考文献：直接用 [来源N] 标注\n"
        f"- **表格**：如果检索到表格且与问题相关，在回答中使用 **[表格:N]** 标记引用，例如「相关数据见 **[表格:2]**」\n"
        f"- **图片**：如果检索到图片且与问题相关，在回答中使用 **[图片:N]** 标记引用，例如「如图所示 **[图片:3]**」\n"
        f"- **代码**：如果检索到代码块且与问题相关，在回答中使用 **[代码:N]** 标记引用\n"
        f"- 每个 **[类型:N]** 标记必须**单独占一行**，前后留空行，前端会自动渲染为对应的内联内容\n"
        f"- 一次回答中可以使用多种标记，前端都能正确渲染\n"
        f"- 不要编造内容，只基于检索结果中提供的信息回答\n\n"
        f"{context_text}"
    )


async def build_rag_context(
    kb_svc: KnowledgeBaseService,
    kb_id: str,
    tenant_id: str,
    query: str,
    top_k: int = 5,
    rerank: bool = True,
) -> RAGContext:
    """执行知识库检索并构建统一 RAG 上下文。"""
    kb = await kb_svc.get_kb(kb_id, tenant_id)
    result = await kb_svc.search(
        kb_id=kb_id,
        query=query,
        tenant_id=tenant_id,
        top_k=top_k,
        rerank=rerank,
    )

    raw_items = result.get("results", [])
    citations = [_item_to_citation(item) for item in raw_items if item.get("chunk_id")]
    context_text = format_context_text(citations)

    return RAGContext(
        query=query,
        kb_id=kb_id,
        kb_name=kb.name,
        citations=citations,
        context_text=context_text,
        total_found=result.get("total_found", len(raw_items)),
        returned=len(citations),
        low_confidence=result.get("low_confidence", False),
        suggestion=result.get("suggestion", ""),
    )


async def search_multiple_kbs(
    kb_svc: KnowledgeBaseService,
    kb_ids: list[str],
    tenant_id: str,
    query: str,
    top_k: int = 5,
    rerank: bool = True,
) -> tuple[list[CitationItem], str, list[str], bool, str]:
    """搜索多个知识库，去重后返回 (citations, context_text, kb_names, low_confidence, suggestion)。"""
    all_citations: list[CitationItem] = []
    seen_ids: set[str] = set()
    kb_names: list[str] = []
    any_low_confidence = False
    best_suggestion = ""

    for kb_id in kb_ids:
        try:
            ctx = await build_rag_context(
                kb_svc, kb_id, tenant_id, query, top_k=top_k, rerank=rerank
            )
            kb_names.append(ctx.kb_name)
            if ctx.low_confidence:
                any_low_confidence = True
                if ctx.suggestion and not best_suggestion:
                    best_suggestion = ctx.suggestion
            for c in ctx.citations:
                if c.chunk_id and c.chunk_id not in seen_ids:
                    seen_ids.add(c.chunk_id)
                    all_citations.append(c)
        except Exception as e:
            logger.warning(f"知识库 {kb_id} 搜索失败: {e}")
            continue

    all_citations.sort(key=lambda x: x.score, reverse=True)
    top = all_citations[:top_k]
    context_text = format_context_text(top)
    return top, context_text, kb_names, any_low_confidence, best_suggestion


def parse_tool_result_citations(result_json: str) -> list[CitationItem]:
    """从工具返回 JSON 解析 citations。"""
    try:
        data = json.loads(result_json)
    except (json.JSONDecodeError, TypeError):
        return []

    citations: list[CitationItem] = []
    for r in data.get("results", []):
        cid = r.get("chunk_id", "")
        if not cid:
            continue
        img_w = r.get("image_width")
        img_h = r.get("image_height")
        citations.append(
            CitationItem(
                chunk_id=cid,
                content=r.get("content", ""),
                source=r.get("source", "未知"),
                page=r.get("page", 1),
                score=float(r.get("score", 0)),
                chunk_type=r.get("chunk_type", "text"),
                section_title=r.get("section_title", ""),
                title=r.get("title") or r.get("section_title", ""),
                document_id=r.get("document_id"),
                table_html=r.get("table_html", ""),
                table_caption=r.get("table_caption", ""),
                image_url=r.get("image_url", ""),
                image_description=r.get("image_description", ""),
                image_caption=r.get("image_caption", ""),
                ocr_status=r.get("ocr_status", ""),
                image_width=int(img_w) if img_w is not None else None,
                image_height=int(img_h) if img_h is not None else None,
            )
        )
    return citations


def merge_citations(
    primary: list[CitationItem],
    secondary: list[CitationItem],
) -> list[CitationItem]:
    """合并 citations，按 chunk_id 去重，保留较高分数。"""
    merged: dict[str, CitationItem] = {}
    for c in primary + secondary:
        if not c.chunk_id:
            continue
        existing = merged.get(c.chunk_id)
        if existing is None or c.score > existing.score:
            merged[c.chunk_id] = c
    return sorted(merged.values(), key=lambda x: x.score, reverse=True)
