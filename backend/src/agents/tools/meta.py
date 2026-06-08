"""Meta — 工具注册表与工具发现。

⚠ 此模块现在从 UnifiedToolRegistry 读取数据，不再维护独立的 _tool_registry。
  保持现有 API 向后兼容，同时新增直接访问统一注册表的能力。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool

from src.harness.unified_registry import UnifiedToolRegistry, get_unified_registry


def _get_registry() -> UnifiedToolRegistry:
    """获取底层统一注册表。"""
    return get_unified_registry()


# ── 向后兼容的 API ──


def register_tool_meta(t: Any) -> None:
    """将工具元信息注册到统一注册表。

    同时注册为 LangChain tool — 之后如果同名的 HarnessTool 到来，会自动合并。
    """
    _get_registry().register(t, source="langchain")


def get_tool_registry() -> dict[str, dict[str, Any]]:
    """获取工具注册表元数据（供 Agent 和 tool_search 使用）。"""
    return _get_registry().get_meta_registry()


def get_default_tools() -> list[Any]:
    """获取 Agent 默认加载的完整 LangChain 工具列表。"""
    return _get_registry().get_langchain_tools()


def get_tools_by_category(category: str) -> list[Any]:
    """按分类获取 LangChain 工具。"""
    entries = _get_registry().list_by_category(category)
    tools: list[Any] = []
    for entry in entries:
        lc_tool = entry.get_langchain_tool()
        if lc_tool is not None:
            tools.append(lc_tool)
    return tools


def _init_registry(tools: list[Any]) -> None:
    """初始化工具注册表（由 __init__.py 调用）。

    将 LangChain 工具批量注册到统一注册表。
    """
    count = _get_registry().register_batch(tools, source="langchain")
    return count  # 无返回值，但供日志使用


# ── tool_search 工具 ──


@tool
def tool_search(query: str = "", category: str = "") -> str:
    """
    搜索当前可用的工具。当不确定该使用哪个工具完成任务时，先调用此工具了解可用选项。
    支持按关键词搜索和按分类过滤。

    Args:
        query: 搜索关键词（模糊匹配工具名和描述），留空返回全部
        category: 分类过滤 — L0-基础/L1-信息/L2-创作/L3-输出/Meta
    """
    results = _get_registry().search(query=query, category=category)

    if not results:
        return json.dumps({
            "message": f"未找到匹配 '{query}' 的工具",
            "all_categories": _get_registry().get_categories(),
            "hint": "尝试 tool_search(query='') 查看全部工具",
        }, ensure_ascii=False)

    return json.dumps({
        "query": query or "(全部)",
        "count": len(results),
        "tools": [
            {
                "name": r["name"],
                "description": r["description"],
                "category": r["category"],
            }
            for r in results
        ],
    }, ensure_ascii=False, indent=2)


# ── 保留 _ALL_TOOLS 兼容引用（静态模块级列表，初始化时使用） ──

_ALL_TOOLS: list[Any] = []


__all__ = [
    "tool_search", "get_default_tools", "get_tool_registry",
    "get_tools_by_category", "register_tool_meta", "_init_registry",
]
