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


def create_kb_search_tool(
    tenant_id: str,
    kb_ids: list[str],
    kb_names: list[str] | None = None,
) -> Any:
    """创建一个绑定到指定知识库的搜索工具（向后兼容接口）。

    内部委托给 KBSearchHarnessTool（HarnessTool 体系），
    返回 LangChain StructuredTool 供 LLM bind_tools。

    Args:
        tenant_id: 租户 ID
        kb_ids: 用户选择的知识库 ID 列表
        kb_names: 知识库名称列表（用于工具描述）

    Returns:
        LangChain StructuredTool（内部由 KBSearchHarnessTool 驱动）
    """
    if not kb_ids:
        raise ValueError("kb_ids 不能为空")

    from src.agents.tools.kb_search import create_kb_search_tool as _factory
    return _factory(tenant_id=tenant_id, kb_ids=kb_ids, kb_names=kb_names)


