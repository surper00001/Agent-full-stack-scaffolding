"""
UnifiedToolRegistry — 统一工具注册表。

所有工具的单一真实来源（Single Source of Truth），替代原有的三重注册表：
  - harness/tool_registry.py 的 _registry（HarnessTool 实例）
  - agents/tools/meta.py 的 _tool_registry（元数据 dict）
  - agents/tools/__init__.py 的 _ALL_TOOLS（LangChain 工具列表）

功能：
  - 同时注册 HarnessTool 和 LangChain @tool
  - 为 graph.py 提供 HarnessTool 查找（调度/权限/AbortSignal）
  - 为 BaseAgent 提供 LangChain 工具列表（LLM bind_tools）
  - 为 tool_search() 提供元数据查询
  - 支持运行时热加载/卸载
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from loguru import logger

# ── 工具条目 ──


@dataclass
class UnifiedToolEntry:
    """注册表中的单条工具记录。"""

    name: str
    description: str
    category: str = "general"
    # 至少有一个非 None
    harness_tool: Any = None  # HarnessTool 实例
    langchain_tool: Any = None  # LangChain @tool / StructuredTool
    # 元数据
    tags: list[str] = field(default_factory=list)
    version: str = "1.0.0"
    source: str = "unknown"  # "builtin" | "skill" | "langchain"
    enabled: bool = True

    def get_langchain_tool(self) -> Any | None:
        """获取可用于 LLM bind_tools 的工具。

        优先级：HarnessTool.to_langchain_tool() > 原始 LangChainTool。
        HarnessTool 包装器包含权限检查、AbortSignal 等安全机制。
        """
        # 优先使用 HarnessTool 的 LangChain 包装器（含安全机制）
        if self.harness_tool is not None:
            return self.harness_tool.to_langchain_tool()
        if self.langchain_tool is not None:
            return self.langchain_tool
        return None

    def get_meta_dict(self) -> dict[str, Any]:
        """获取 tool_search 所需的元数据。"""
        return {
            "name": self.name,
            "description": self.description.split("\n")[0] if self.description else "",
            "full_description": self.description or "",
            "category": self.category,
            "tags": self.tags,
            "source": self.source,
        }


# ── 统一注册表 ──


class UnifiedToolRegistry:
    """
    统一工具注册表 —— 全局单例。

    使用方式:
        registry = get_unified_registry()
        registry.register(harness_tool_or_langchain_tool)
        tools = registry.get_langchain_tools()
    """

    def __init__(self) -> None:
        self._entries: dict[str, UnifiedToolEntry] = {}

    # ── 注册 / 注销 ──

    def register(
        self,
        tool: Any,
        *,
        category: str | None = None,
        source: str = "unknown",
    ) -> UnifiedToolEntry:
        """
        注册一个工具。接受 HarnessTool 或 LangChain @tool/StructuredTool。

        注册优先级：
          1. 如果是 HarnessTool 实例 → 自动提取 name/description/category
          2. 如果是 LangChain tool → 提取 name/description，category 需手动指定或自动推断
          3. 如果同名工具已存在 → 更新（合并 HarnessTool + LangChainTool）
        """
        from src.harness.tool_base import HarnessTool

        if isinstance(tool, HarnessTool):
            return self._register_harness_tool(tool, source=source)
        else:
            return self._register_langchain_tool(tool, category=category, source=source)

    def _register_harness_tool(
        self, tool: Any, *, source: str = "builtin"
    ) -> UnifiedToolEntry:
        """注册 HarnessTool 实例。"""
        raw_category = getattr(tool, "category", "general")
        # 标准化分类：HarnessTool 原生分类 → L0-L3 体系
        category = _normalize_category(raw_category, tool.name)

        entry = self._entries.get(tool.name)

        if entry is None:
            entry = UnifiedToolEntry(
                name=tool.name,
                description=tool.description,
                category=category,
                harness_tool=tool,
                tags=list(getattr(tool, "tags", [])),
                version=getattr(tool, "version", "1.0.0"),
                source=source,
            )
            self._entries[tool.name] = entry
            logger.debug(f"[UnifiedRegistry] 注册 HarnessTool: {tool.name}")
        else:
            # 更新已有条目 — 保留已有分类（LangChain 注册时已推断）
            entry.harness_tool = tool
            if entry.description == "":
                entry.description = tool.description
            logger.debug(f"[UnifiedRegistry] 更新 HarnessTool: {tool.name}")

        return entry

    def _register_langchain_tool(
        self,
        tool: Any,
        *,
        category: str | None = None,
        source: str = "langchain",
    ) -> UnifiedToolEntry:
        """注册 LangChain @tool 或 StructuredTool。"""
        name = getattr(tool, "name", getattr(tool, "__name__", "unknown"))
        desc = getattr(tool, "description", "")

        entry = self._entries.get(name)

        if entry is None:
            entry = UnifiedToolEntry(
                name=name,
                description=desc,
                category=category or _infer_category(name),
                langchain_tool=tool,
                source=source,
            )
            self._entries[name] = entry
            logger.debug(f"[UnifiedRegistry] 注册 LangChainTool: {name}")
        else:
            # 更新已有条目
            if entry.langchain_tool is None:
                entry.langchain_tool = tool
            if entry.description == "" and desc:
                entry.description = desc
            logger.debug(f"[UnifiedRegistry] 更新 LangChainTool: {name}")

        return entry

    def unregister(self, name: str) -> UnifiedToolEntry | None:
        """注销工具。"""
        return self._entries.pop(name, None)

    def register_batch(
        self,
        tools: list[Any],
        *,
        category: str | None = None,
        source: str = "unknown",
    ) -> int:
        """批量注册工具。返回注册数量。"""
        count = 0
        for t in tools:
            self.register(t, category=category, source=source)
            count += 1
        return count

    # ── 查询 ──

    def get(self, name: str) -> UnifiedToolEntry | None:
        """按名称获取工具条目。"""
        return self._entries.get(name)

    def get_harness_tool(self, name: str) -> Any | None:
        """获取 HarnessTool 实例（供 graph.py 调度/执行使用）。"""
        entry = self._entries.get(name)
        if entry and entry.harness_tool is not None:
            return entry.harness_tool
        return None

    def get_langchain_tool(self, name: str) -> Any | None:
        """获取 LangChain 工具实例。"""
        entry = self._entries.get(name)
        if entry is None:
            return None
        return entry.get_langchain_tool()

    def get_langchain_tools(self) -> list[Any]:
        """获取所有可用于 LLM bind_tools 的工具列表。"""
        tools: list[Any] = []
        for entry in self._entries.values():
            if not entry.enabled:
                continue
            lc_tool = entry.get_langchain_tool()
            if lc_tool is not None:
                tools.append(lc_tool)
        return tools

    def get_meta_registry(self) -> dict[str, dict[str, Any]]:
        """获取 tool_search() 所需的工具元数据字典。"""
        return {
            name: entry.get_meta_dict()
            for name, entry in self._entries.items()
            if entry.enabled
        }

    def search(
        self,
        query: str = "",
        category: str = "",
    ) -> list[dict[str, Any]]:
        """搜索工具（供 tool_search 使用）。"""
        results: list[dict[str, Any]] = []
        for name, entry in self._entries.items():
            if name == "tool_search":  # 不搜索自身
                continue
            if not entry.enabled:
                continue

            meta = entry.get_meta_dict()
            q = query.lower()
            if q and q not in name.lower() and q not in meta["description"].lower():
                continue
            if category and meta["category"] != category:
                continue

            results.append(meta)

        return results

    def list_all(self) -> list[UnifiedToolEntry]:
        """列出所有工具条目。"""
        return list(self._entries.values())

    def list_by_category(self, category: str) -> list[UnifiedToolEntry]:
        """按分类列出工具。"""
        return [e for e in self._entries.values() if e.category == category and e.enabled]

    def list_by_source(self, source: str) -> list[UnifiedToolEntry]:
        """按来源列出工具。"""
        return [e for e in self._entries.values() if e.source == source]

    def get_categories(self) -> list[str]:
        """获取所有分类。"""
        cats: set[str] = set()
        for entry in self._entries.values():
            if entry.enabled:
                cats.add(entry.category)
        return sorted(cats)

    # ── 管理 ──

    def enable(self, name: str) -> bool:
        """启用工具。"""
        entry = self._entries.get(name)
        if entry:
            entry.enabled = True
            return True
        return False

    def disable(self, name: str) -> bool:
        """禁用工具（不删除，只是不可用）。"""
        entry = self._entries.get(name)
        if entry:
            entry.enabled = False
            return True
        return False

    def clear(self) -> int:
        """清空注册表。返回清除数量。"""
        count = len(self._entries)
        self._entries.clear()
        return count

    @property
    def count(self) -> int:
        """已注册工具数。"""
        return len(self._entries)

    @property
    def enabled_count(self) -> int:
        """启用的工具数。"""
        return sum(1 for e in self._entries.values() if e.enabled)


# ── 分类推断与标准化 ──

# HarnessTool 原生分类 → 统一分类体系
_HARNESS_CATEGORY_MAP: dict[str, str] = {
    "file": "L0-基础",
    "shell": "L0-基础",
    "network": "L1-信息",
    "skill": "L2-创作",
    "meta": "Meta",
    "general": "General",
}


def _normalize_category(raw_category: str, tool_name: str) -> str:
    """将 HarnessTool 原生分类标准化为统一分类体系。"""
    if raw_category in _HARNESS_CATEGORY_MAP:
        return _HARNESS_CATEGORY_MAP[raw_category]
    return raw_category


def _infer_category(name: str) -> str:
    """从工具名推断分类。"""
    cats: dict[str, str] = {
        "calculator": "L0-基础",
        "current_time": "L0-基础",
        "web_search": "L1-信息",
        "search_knowledge_base": "L1-信息",
        "analyze_trending_topics": "L1-信息",
        "fetch_url_outline": "L1-信息",
        "generate_video_script": "L2-创作",
        "generate_storyboard": "L2-创作",
        "generate_shot_list": "L2-创作",
        "generate_mindmap": "L2-创作",
        "edit_mindmap": "L2-创作",
        "generate_resume_docx": "L2-创作",
        "generate_cover_letter_docx": "L2-创作",
        "save_markdown_file": "L3-输出",
        "save_text_file": "L3-输出",
        "save_srt_subtitle": "L3-输出",
        "export_mindmap": "L3-输出",
        "tool_search": "Meta",
        "read_file": "L0-基础",
        "write_file": "L0-基础",
        "edit_file": "L0-基础",
        "glob": "L0-基础",
        "grep": "L0-基础",
        "list_dir": "L0-基础",
        "run_shell": "L0-基础",
        "web_fetch": "L1-信息",
        "web_request": "L1-信息",
    }
    return cats.get(name, "General")


# ── 全局单例 ──

_registry_singleton: UnifiedToolRegistry | None = None


def get_unified_registry() -> UnifiedToolRegistry:
    """获取 UnifiedToolRegistry 全局单例。"""
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = UnifiedToolRegistry()
    return _registry_singleton


def reset_unified_registry() -> UnifiedToolRegistry:
    """重置全局单例（测试用）。"""
    global _registry_singleton
    _registry_singleton = UnifiedToolRegistry()
    return _registry_singleton
