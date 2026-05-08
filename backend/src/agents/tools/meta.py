"""Meta — 工具注册表与工具发现。"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool



# 全局工具注册表，在模块加载时填充
_tool_registry: dict[str, dict[str, Any]] = {}


def register_tool_meta(t: Any) -> None:
    """将工具元信息注册到全局注册表。"""
    _tool_registry[t.name] = {
        "name": t.name,
        "description": t.description.split("\n")[0] if t.description else "",
        "full_description": t.description or "",
        "category": _categorize_tool(t.name),
    }


def _categorize_tool(name: str) -> str:
    cats = {
        "calculator": "L0-基础", "current_time": "L0-基础",
        "web_search": "L1-信息", "analyze_trending_topics": "L1-信息",
        "generate_video_script": "L2-创作", "generate_storyboard": "L2-创作",
        "generate_shot_list": "L2-创作",
        "save_markdown_file": "L3-输出", "save_text_file": "L3-输出",
        "save_srt_subtitle": "L3-输出",
        "tool_search": "Meta",
    }
    return cats.get(name, "Unknown")


@tool
def tool_search(query: str = "", category: str = "") -> str:
    """
    搜索当前可用的工具。当不确定该使用哪个工具完成任务时，先调用此工具了解可用选项。
    支持按关键词搜索和按分类过滤。

    Args:
        query: 搜索关键词（模糊匹配工具名和描述），留空返回全部
        category: 分类过滤 — L0-基础/L1-信息/L2-创作/L3-输出
    """
    results = []
    for name, meta in _tool_registry.items():
        if name == "tool_search":
            continue
        q = query.lower()
        if q and q not in name.lower() and q not in meta["description"].lower():
            continue
        if category and meta["category"] != category:
            continue
        results.append({
            "name": meta["name"],
            "description": meta["description"],
            "category": meta["category"],
        })

    if not results:
        return json.dumps({
            "message": f"未找到匹配 '{query}' 的工具",
            "all_categories": ["L0-基础", "L1-信息", "L2-创作", "L3-输出"],
            "hint": "尝试 tool_search(query='') 查看全部工具",
        }, ensure_ascii=False)

    return json.dumps({
        "query": query or "(全部)",
        "count": len(results),
        "tools": results,
    }, ensure_ascii=False, indent=2)




_ALL_TOOLS: list[Any] = []


def get_default_tools() -> list[Any]:
    """获取 Agent 默认加载的完整工具列表。"""
    return list(_ALL_TOOLS)


def get_tool_registry() -> dict[str, dict[str, Any]]:
    """获取工具注册表（供 Agent 和 ToolNode 使用）。"""
    return dict(_tool_registry)


def get_tools_by_category(category: str) -> list[Any]:
    """按分类获取工具。"""
    return [t for t in _ALL_TOOLS if _categorize_tool(t.name) == category]


def _init_registry(tools: list[Any]) -> None:
    """初始化工具注册表（由 __init__.py 调用）。"""
    global _ALL_TOOLS
    _ALL_TOOLS = list(tools)
    for t in tools:
        register_tool_meta(t)


__all__ = [
    "tool_search", "get_default_tools", "get_tool_registry",
    "get_tools_by_category", "register_tool_meta", "_init_registry",
]
