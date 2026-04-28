"""
RAG 上下文构建器 —— 统一检索结果格式化，供聊天预检索与 Agent 工具复用。
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
    """单条引用来源。"""

    chunk_id: str
    content: str
    source: str
    page: int
    score: float
    chunk_type: str = "text"
    section_title: str = ""
    document_id: str | None = None


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
                    "document_id": c.document_id,
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
    section = meta.get("section_title", "") if isinstance(meta, dict) else ""
    return CitationItem(
        chunk_id=item.get("chunk_id", ""),
        content=item.get("expanded_content") or item.get("content", ""),
        source=item.get("document_filename", "未知"),
        page=item.get("page_start", 1),
        score=float(item.get("score", 0)),
        chunk_type=item.get("chunk_type", "text"),
        section_title=section,
        document_id=item.get("document_id"),
    )


def format_context_text(citations: list[CitationItem]) -> str:
    """将引用列表格式化为 LLM 可读的上下文文本。"""
    parts: list[str] = []
    for i, c in enumerate(citations):
        source_info = f"[来源{i + 1}] {c.source}"
        if c.section_title:
            source_info += f" > {c.section_title}"
        source_info += f" (第{c.page}页, 匹配度:{c.score:.0%})"
        parts.append(f"{source_info}\n{c.content}")
    return "\n\n---\n\n".join(parts)


def build_system_rag_prompt(kb_name: str, context_text: str) -> str:
    """构建注入 system prompt 的 RAG 段落。"""
    if not context_text.strip():
        return ""
    return (
        f"\n\n## 知识库检索结果（自动）\n"
        f"以下是从知识库「{kb_name}」检索到的相关内容，请优先基于这些信息回答，并标注来源。\n\n"
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
    )


async def search_multiple_kbs(
    kb_svc: KnowledgeBaseService,
    kb_ids: list[str],
    tenant_id: str,
    query: str,
    top_k: int = 5,
    rerank: bool = True,
) -> tuple[list[CitationItem], str, list[str]]:
    """搜索多个知识库，去重后返回 citations、context_text、kb_names。"""
    all_citations: list[CitationItem] = []
    seen_ids: set[str] = set()
    kb_names: list[str] = []

    for kb_id in kb_ids:
        try:
            ctx = await build_rag_context(
                kb_svc, kb_id, tenant_id, query, top_k=top_k, rerank=rerank
            )
            kb_names.append(ctx.kb_name)
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
    return top, context_text, kb_names


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
        citations.append(
            CitationItem(
                chunk_id=cid,
                content=r.get("content", ""),
                source=r.get("source", "未知"),
                page=r.get("page", 1),
                score=float(r.get("score", 0)),
                chunk_type=r.get("chunk_type", "text"),
                section_title=r.get("section_title", ""),
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
