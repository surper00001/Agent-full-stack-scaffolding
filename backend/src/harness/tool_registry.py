"""
Skill Registry — DB-backed 工具注册表。

启动时加载内置工具 + DB 中的 active Skill。
支持运行时热加载，AI 生成的 Skill 通过此注册表接入 Agent。
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from src.harness.tool_base import HarnessTool

# 全局工具注册表（内存缓存）
_registry: dict[str, HarnessTool] = {}


def register_tool(tool: HarnessTool) -> None:
    """注册单个工具。"""
    _registry[tool.name] = tool


def unregister_tool(name: str) -> HarnessTool | None:
    """注销工具。"""
    return _registry.pop(name, None)


def get_tool(name: str) -> HarnessTool | None:
    """按名称获取工具。"""
    return _registry.get(name)


def get_tool_registry() -> dict[str, HarnessTool]:
    """获取当前完整工具注册表。"""
    return dict(_registry)


def list_tools(
    category: str | None = None,
    enabled_only: bool = True,
) -> list[HarnessTool]:
    """列出工具。"""
    tools = list(_registry.values())
    if category:
        tools = [t for t in tools if t.category == category]
    if enabled_only:
        tools = [t for t in tools if t.is_enabled()]
    return tools


def register_builtin_tools() -> int:
    """注册所有内置工具（在应用启动时调用）。"""
    # 文件系统工具
    from src.agents.tools.file_tools import (
        EditFileTool,
        GlobTool,
        GrepTool,
        ListDirTool,
        ReadFileTool,
        WriteFileTool,
    )

    # Shell 工具
    from src.agents.tools.shell_tool import RunShellTool

    # 网络工具
    from src.agents.tools.network_tools import WebFetchTool, WebRequestTool

    builtins: list[HarnessTool] = [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        GlobTool(),
        GrepTool(),
        ListDirTool(),
        RunShellTool(),
        WebFetchTool(),
        WebRequestTool(),
    ]

    for tool in builtins:
        register_tool(tool)

    logger.info(f"已注册 {len(builtins)} 个内置 Harness 工具")
    return len(builtins)


async def load_skills_from_db(session: Any) -> int:
    """从 DB 加载所有 active Skill 并注册。"""
    from src.services.skill_service import SkillService

    service = SkillService(session)
    skills = await service.list_active_skills()

    count = 0
    for skill in skills:
        try:
            tool = _skill_to_tool(skill)
            register_tool(tool)
            count += 1
        except Exception as e:
            logger.error(f"加载 Skill '{skill.name}' 失败: {e}")

    logger.info(f"从 DB 加载了 {count} 个 Skill 工具")
    return count


def _skill_to_tool(skill: Any) -> HarnessTool:
    """将 Skill ORM 模型转换为 HarnessTool 实例。"""
    import hashlib
    import json
    from types import ModuleType
    from typing import ClassVar

    from pydantic import BaseModel, create_model

    # 解析 input_schema → 动态创建 Pydantic Model
    if skill.input_schema:
        schema_dict = json.loads(skill.input_schema)
        fields = {}
        for prop_name, prop_info in schema_dict.get("properties", {}).items():
            prop_type = _json_type_to_python(prop_info)
            required = prop_name in schema_dict.get("required", [])
            default = ... if required else (prop_info.get("default", None))
            description = prop_info.get("description", "")
            fields[prop_name] = (prop_type, Field(default=default, description=description))
        input_model = create_model(f"{skill.name}_Input", **fields) if fields else create_model(f"{skill.name}_Input")
    else:
        input_model = create_model(f"{skill.name}_Input")

    class DynamicSkillTool(HarnessTool):
        name: ClassVar[str] = skill.name
        description: ClassVar[str] = skill.description
        input_schema: ClassVar[type[BaseModel]] = input_model
        category: ClassVar[str] = skill.category
        version: ClassVar[str] = skill.version
        requires_sandbox: ClassVar[bool] = skill.requires_sandbox

        def is_read_only(self, input: Any) -> bool:
            return skill.is_read_only

        def is_concurrency_safe(self, input: Any) -> bool:
            return skill.is_concurrency_safe

        async def execute(self, input: Any, signal: Any) -> Any:
            # 代码完整性校验
            if skill.code_hash:
                computed = hashlib.sha256(skill.code.encode()).hexdigest()
                if computed != skill.code_hash:
                    raise RuntimeError(f"Skill '{skill.name}' 代码校验失败，可能被篡改")

            # 编译并执行 Skill 代码
            restricted_globals: dict[str, Any] = {
                "__builtins__": {
                    k: v for k, v in __builtins__.__dict__.items()  # type: ignore[attr-defined]
                    if k in (
                        "print", "len", "range", "enumerate", "zip", "map", "filter",
                        "list", "dict", "set", "tuple", "str", "int", "float", "bool",
                        "isinstance", "type", "Exception", "ValueError", "TypeError",
                        "KeyError", "IndexError", "AttributeError", "RuntimeError",
                        "abs", "min", "max", "sum", "sorted", "reversed", "round",
                        "any", "all", "iter", "next", "slice",
                    )
                },
                "json": json,
                "__name__": f"skill_{skill.name}",
            }
            restricted_locals: dict[str, Any] = {}

            code = compile(skill.code, f"<skill:{skill.name}>", "exec")
            exec(code, restricted_globals, restricted_locals)

            func = restricted_locals.get("execute")
            if func is None:
                raise RuntimeError(f"Skill '{skill.name}' 未定义 execute 函数")

            signal.throw_if_aborted()
            import asyncio as _asyncio
            if _asyncio.iscoroutinefunction(func):
                return await func(input.model_dump())
            return func(input.model_dump())

    return DynamicSkillTool()


def _json_type_to_python(prop_info: dict) -> type:
    """将 JSON Schema 类型映射为 Python 类型。"""
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "array": list,
        "object": dict,
    }
    json_type = prop_info.get("type", "string")
    return type_map.get(json_type, str)
