"""
Query 改写服务 —— 提升短 query 检索召回率。

核心思路（HyDE — Hypothetical Document Embeddings）：
短 query 的语义密度低，向量+BM25 难以在文档中精确匹配。
通过 LLM 先生成一段"假设文档片段"，再对假设文档做 embedding 检索，
其语义空间更接近真实文档，召回率显著提升。

触发条件：
- query 字符数 < kb_query_rewrite_min_chars（默认 20）
- kb_query_rewrite_enabled = True

降级策略：
- LLM 调用失败 → 静默降级为原 query
- 改写后的 query 用于 embedding 和 BM25 检索，原始 query 仍用于 reranker
"""

from __future__ import annotations

import re

from loguru import logger

from src.core.config import get_settings

# ── HyDE Prompt ────────────────────────────────────────────

_HYDE_SYSTEM_PROMPT = (
    "你是一个文档助手。用户有一个简短的问题，你需要根据问题生成一段"
    "可能出现在相关文档中的描述性内容。"
    "不要回答这个问题，而是写一段像文档中会出现的回答内容。"
    "使用中文，保持客观、信息密集、像技术文档风格。"
    "只输出生成的文档段落，不要加任何前缀、解释或标记。"
    "字数控制在 100-200 字。"
)

# 检测是否已经是改写后的文本（避免重复改写）
_ALREADY_REWRITTEN_PATTERNS = [
    re.compile(r"根据.*文档", re.IGNORECASE),
    re.compile(r"以下(是|为).*(介绍|说明|描述|内容)"),
    re.compile(r"该(文档|章节|部分).*(介绍|描述|说明|包含)"),
]


def _looks_already_rewritten(text: str) -> bool:
    """检测文本是否已经是 HyDE 改写后的文档风格。"""
    return any(p.search(text) for p in _ALREADY_REWRITTEN_PATTERNS)


def _build_hyde_prompt(query: str) -> str:
    """构造 HyDE 假设文档生成 prompt。"""
    return (
        f"{_HYDE_SYSTEM_PROMPT}\n\n"
        f"用户问题：{query}\n\n"
        f"请生成一段可能回答此问题的文档段落："
    )


# ── 公开 API ───────────────────────────────────────────────


def should_rewrite(query: str) -> bool:
    """判断是否需要对 query 做改写。"""
    settings = get_settings()
    if not settings.kb_query_rewrite_enabled:
        return False
    if len(query) >= settings.kb_query_rewrite_min_chars:
        return False
    if _looks_already_rewritten(query):
        return False
    return True


async def rewrite_query(query: str) -> str:
    """对短 query 做 HyDE 改写，返回改写后的文本。

    LLM 调用失败时静默降级为原始 query。
    """
    settings = get_settings()

    if not should_rewrite(query):
        return query

    try:
        from src.llm.factory import LLMFactory

        factory = LLMFactory(settings)
        model_name = settings.kb_query_rewrite_model or None
        llm = factory.create_chat_model(
            model_name=model_name,
            temperature=0.3,
            max_tokens=300,
        )

        prompt = _build_hyde_prompt(query)
        result = await llm.ainvoke(prompt)
        rewritten = result.content.strip() if hasattr(result, "content") else str(result).strip()

        # 清理可能的引号包裹
        if rewritten.startswith('"') and rewritten.endswith('"'):
            rewritten = rewritten[1:-1]
        if rewritten.startswith("「") and rewritten.endswith("」"):
            rewritten = rewritten[1:-1]

        if len(rewritten) < 5:
            logger.warning(f"HyDE 改写结果过短，降级为原 query: {query[:60]}")
            return query

        logger.info(
            f"[Query改写] 原query({len(query)} chars): '{query[:80]}' "
            f"→ 改写({len(rewritten)} chars): '{rewritten[:120]}'"
        )
        return rewritten

    except Exception as e:
        logger.warning(f"Query 改写失败，降级为原 query: {e}")
        return query
