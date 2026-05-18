"""L1 信息获取工具 — Web 搜索、知识库检索。"""

from __future__ import annotations

import json
from typing import Any

import httpx
from langchain_core.tools import tool
from loguru import logger

from src.core.config import get_settings



def _extract_bocha_web_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从博查 API 响应提取网页列表（兼容 data.webPages.value 与顶层 webPages）。"""
    web_pages = data.get("data", {}).get("webPages") or data.get("webPages")
    if web_pages is None:
        return []
    if isinstance(web_pages, list):
        return web_pages
    if isinstance(web_pages, dict):
        value = web_pages.get("value")
        if isinstance(value, list):
            return value
    return []


@tool
def web_search(query: str, count: int = 5) -> str:
    """
    使用博查搜索引擎搜索互联网，获取最新信息、热点话题、行业知识。
    适用于：市场调研、热点追踪、素材搜集、事实核查。

    Args:
        query: 搜索关键词
        count: 返回结果数量，默认 5，最大 10
    """
    settings = get_settings()
    api_key = settings.bocha_api_key.get_secret_value()
    if not api_key:
        return "博查搜索 API Key 未配置，请联系管理员设置 BOCHA_API_KEY。"

    try:
        resp = httpx.post(
            settings.bocha_api_base,
            json={
                "query": query,
                "count": min(count, 10),
                "summary": True,
                "freshness": "noLimit",
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in _extract_bocha_web_items(data)[:count]:
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet") or item.get("summary", ""),
            })

        if not results:
            return f"未找到与“{query}”相关的结果。"

        return json.dumps({"query": query, "results": results}, ensure_ascii=False, indent=2)
    except httpx.TimeoutException:
        logger.warning(f"Web 搜索超时: query={query!r}")
        return f"搜索“{query}”超时，请稍后重试。"
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Web 搜索 HTTP 错误: {e.response.status_code} | url={settings.bocha_api_base}"
        )
        return f"搜索失败: HTTP {e.response.status_code}（请检查 BOCHA_API_BASE 与 API Key）"
    except Exception as e:
        logger.error(f"Web 搜索失败: {e}")
        return f"搜索失败: {e}"




_KB_SEARCH_TOOL_NAME = "search_knowledge_base"


def _build_kb_search_description(kb_names: list[str]) -> str:
    """构建 KB 搜索工具的描述文本。"""
    kb_list = "、".join(kb_names) if kb_names else "用户的知识库"
    return (
        f"搜索用户的知识库（{kb_list}）中的文档内容。"
        "当用户的问题涉及已有文档、需要查找内部资料、询问项目相关内容时使用此工具。"
        "支持自然语言查询，返回最相关的文档片段及其来源信息。\n\n"
        "Args:\n"
        "    query: 自然语言搜索查询，如 \"JWT 认证流程\" 或 \"API 接口文档\"\n"
        "    top_k: 返回结果数量，默认 5，最大 10\n\n"
        "Returns: JSON 格式的搜索结果，包含 content（内容）、source（来源文件）、"
        "page（页码）、score（匹配分数 0-1）、chunk_id（分块ID）"
    )


def create_kb_search_tool(
    tenant_id: str,
    kb_ids: list[str],
    kb_names: list[str] | None = None,
) -> Any:
    """创建一个绑定到指定知识库的搜索工具。

    采用工厂模式：每次对话创建 Agent 时，根据用户选择的知识库动态构建工具。
    工具内部通过独立的 DB session 访问知识库服务。

    Args:
        tenant_id: 租户 ID
        kb_ids: 用户选择的知识库 ID 列表
        kb_names: 知识库名称列表（用于工具描述）

    Returns:
        绑定到指定知识库的 langchain Tool
    """
    if not kb_ids:
        raise ValueError("kb_ids 不能为空")

    display_names = kb_names or [f"知识库{i+1}" for i in range(len(kb_ids))]
    desc = _build_kb_search_description(display_names)

    @tool
    def search_knowledge_base(query: str, top_k: int = 5) -> str:
        """搜索用户的知识库。Agent 在需要查找文档资料时自动调用。"""
        import asyncio

        from src.db.session import AsyncSessionLocal
        from src.services.knowledge_base_service import KnowledgeBaseService

        async def _search() -> str:
            from src.services.rag.context_builder import search_multiple_kbs

            async with AsyncSessionLocal() as session:
                kb_svc = KnowledgeBaseService(session)
                top, context_text, _ = await search_multiple_kbs(
                    kb_svc=kb_svc,
                    kb_ids=kb_ids,
                    tenant_id=tenant_id,
                    query=query,
                    top_k=min(top_k, 10),
                    rerank=True,
                )

            if not top:
                return json.dumps({
                    "query": query,
                    "total_found": 0,
                    "results": [],
                    "hint": "知识库中未找到相关内容，建议使用 web_search 搜索互联网或请用户提供更多信息。",
                }, ensure_ascii=False)

            results = [
                {
                    "content": c.content,
                    "source": c.source,
                    "page": c.page,
                    "score": c.score,
                    "chunk_id": c.chunk_id,
                    "chunk_type": c.chunk_type,
                    "section_title": c.section_title,
                    "image_url": c.image_url,
                    "image_description": c.image_description,
                    "image_caption": c.image_caption,
                    "ocr_status": c.ocr_status,
                }
                for c in top
            ]

            return json.dumps({
                "query": query,
                "total_found": len(results),
                "returned": len(results),
                "results": results,
                "context_for_llm": context_text,
            }, ensure_ascii=False, indent=2)

        # 在同步上下文中运行异步搜索
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _search())
                    return future.result(timeout=30)
            return asyncio.run(_search())
        except RuntimeError:
            return asyncio.run(_search())
        except Exception as e:
            logger.error(f"知识库搜索异常: {e}")
            return json.dumps({
                "query": query,
                "error": str(e),
                "results": [],
            }, ensure_ascii=False)

    # 覆盖工具名和描述
    search_knowledge_base.name = _KB_SEARCH_TOOL_NAME
    search_knowledge_base.description = desc

    return search_knowledge_base


