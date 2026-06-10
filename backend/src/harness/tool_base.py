"""
HarnessTool — 统一工具接口。

核心理念：
- Pydantic v2 BaseModel 做输入校验（Python 版 Zod）
- 自动生成 JSON Schema 供 LLM function calling
- is_read_only / is_concurrency_safe 区分 → 驱动并行调度
- AbortSignal 支持可组合取消

设计参考：Anthropic Tool Use 接口 + 自定义调度增强

使用示例：
    class ReadFileInput(BaseModel):
        file_path: str = Field(description="要读取的文件绝对路径")
        offset: int = Field(default=0, description="起始行号")
        limit: int = Field(default=200, description="读取行数")

    class ReadFileTool(HarnessTool[ReadFileInput, str]):
        name = "read_file"
        description = "读取文件内容，支持分页"
        input_schema = ReadFileInput

        def is_read_only(self, input: ReadFileInput) -> bool:
            return True  # 读文件是只读的

        def is_concurrency_safe(self, input: ReadFileInput) -> bool:
            return False  # 同一个文件指针可能冲突

        async def execute(self, input: ReadFileInput, signal: AbortSignal) -> str:
            signal.throw_if_aborted()
            # ... 实现
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, ClassVar, Generic, TypeVar, cast

from pydantic import BaseModel

from src.harness.abort_signal import AbortSignal

# ── 泛型参数 ──
Input = TypeVar("Input", bound=BaseModel)
Output = TypeVar("Output")


# ── 结果类型 ──

@dataclass
class ValidationResult:
    """输入校验结果。"""
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def ok(cls, warnings: list[str] | None = None) -> ValidationResult:
        return cls(valid=True, warnings=warnings or [])

    @classmethod
    def fail(cls, errors: list[str]) -> ValidationResult:
        return cls(valid=False, errors=errors)


@dataclass
class PermissionResult:
    """权限校验结果。"""
    allowed: bool
    reason: str = ""
    requires_approval: bool = False  # 是否需要人工审批


# ── 工具执行结果 ──

@dataclass
class ToolResult:
    """工具执行完整结果。"""
    tool_name: str
    success: bool
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def ok(cls, name: str, output: Any, **meta) -> ToolResult:
        return cls(tool_name=name, success=True, output=output, metadata=meta)

    @classmethod
    def fail(cls, name: str, error: str, **meta) -> ToolResult:
        return cls(tool_name=name, success=False, error=error, metadata=meta)


# ── 抽象基类 ──

class HarnessTool(ABC, Generic[Input, Output]):
    """
    统一工具接口。

    子类需要定义：
    - name: str            — 唯一标识
    - description: str     — 给 LLM 看的使用说明（决定何时调用）
    - input_schema: type[BaseModel] — Pydantic Model，自动生成 JSON Schema
    - execute(input, signal) — 核心逻辑

    可选覆盖：
    - is_enabled()         — Feature Flag / 环境检查
    - is_read_only(input)  — 只读 → 可以和其他只读工具并行
    - is_concurrency_safe(input) — 真正并发安全 → 不受限制并行
    - validate_input(input)— 业务级校验（Pydantic 校验之后）
    - check_permissions(input) — 权限检查
    - render_result(output)— 格式化给人看的结果
    - render_tool_use(input) — 格式化工具调用的展示
    """

    # ── 子类必须定义 ──
    name: ClassVar[str]
    description: ClassVar[str]
    input_schema: ClassVar[type[BaseModel]]

    # ── 元数据（可选覆盖） ──
    category: ClassVar[str] = "general"  # file / shell / network / skill / meta
    version: ClassVar[str] = "1.0.0"
    tags: ClassVar[list[str]] = []
    requires_sandbox: ClassVar[bool] = False  # 是否必须在沙箱中运行

    # ── 调度信息 ──

    def is_enabled(self) -> bool:
        """工具是否当前可用（Feature Flag / 环境判断）。"""
        return True

    def is_read_only(self, input: Input) -> bool:  # noqa: ARG002
        """是否只读。

        只读工具可以和其它只读工具并行执行。
        注意：只读 ≠ 并发安全（如读取同一个文件指针）。
        """
        return False

    def is_concurrency_safe(self, input: Input) -> bool:  # noqa: ARG002
        """是否真正的并发安全。

        并发安全的工具不受限制地并行执行。
        非并发安全的工具在调度时互斥。
        """
        return False

    # ── 生命周期 ──

    def validate_input(self, input: Input) -> ValidationResult:  # noqa: ARG002
        """
        业务级输入校验。

        Pydantic 已完成类型/必填校验，此方法做额外的业务规则校验。
        如：文件路径必须在 workspace 内、URL 必须白名单等。
        """
        return ValidationResult.ok()

    def check_permissions(self, input: Input) -> PermissionResult:  # noqa: ARG002
        """权限校验。默认允许。"""
        return PermissionResult(allowed=True)

    # ── 核心执行 ──

    @abstractmethod
    async def execute(self, input: Input, signal: AbortSignal) -> Output:
        """
        执行工具核心逻辑。

        实现要点：
        1. 定期调用 signal.throw_if_aborted() 支持中途取消
        2. 异常会被框架捕获，包装为 ToolResult
        3. 这是唯一必须实现的方法
        """
        ...

    # ── 渲染 ──

    def render_result(self, output: Output) -> str:
        """将执行结果格式化为人类可读的字符串。

        用于在前端展示工具执行结果（非 LLM 消费）。
        """
        if isinstance(output, str):
            return output
        return json.dumps(output, ensure_ascii=False, indent=2)

    def render_tool_use(self, input: Input) -> str:
        """将工具调用格式化为人类可读的字符串。

        用于在前端展示"正在执行什么操作"。
        """
        return json.dumps(input.model_dump(), ensure_ascii=False, indent=2)

    # ── JSON Schema 生成（给 LLM function calling） ──

    @classmethod
    def to_openai_function(cls) -> dict[str, Any]:
        """生成 OpenAI function calling 格式的工具定义。"""
        schema = cls.input_schema.model_json_schema()
        # 去除 Pydantic 特有字段，保留标准 JSON Schema
        clean_schema = {
            "type": "object",
            "properties": schema.get("properties", {}),
            "required": schema.get("required", []),
        }
        return {
            "type": "function",
            "function": {
                "name": cls.name,
                "description": cls.description,
                "parameters": clean_schema,
            },
        }

    @classmethod
    def to_langchain_tool(cls) -> Any:
        """
        将 HarnessTool 包装为 LangChain StructuredTool。

        LangChain 的 StructuredTool 内置了 args_schema 支持，
        正好映射到 input_schema (Pydantic Model)。
        """
        from langchain_core.tools import StructuredTool

        async def _execute(**kwargs: Any) -> Any:
            input_obj = cls.input_schema(**kwargs)
            signal = AbortSignal(name=f"tool-{cls.name}")
            start = time.perf_counter()
            try:
                # 权限检查
                typed_input = cast("Input", input_obj)
                perm = cls().check_permissions(typed_input)
                if not perm.allowed:
                    return f"[权限拒绝] {perm.reason}"
                # 执行
                result = await cls().execute(typed_input, signal)
                (time.perf_counter() - start) * 1000
                return cls().render_result(result)
            except Exception as e:
                return f"[工具执行失败] {type(e).__name__}: {e}"

        return StructuredTool(
            name=cls.name,
            description=cls.description,
            args_schema=cls.input_schema,
            coroutine=_execute,
        )

    # ── 工具信息摘要 ──

    @classmethod
    def get_info(cls) -> dict[str, Any]:
        """返回工具元信息，供 tool_search 查询。"""
        return {
            "name": cls.name,
            "description": cls.description,
            "category": cls.category,
            "version": cls.version,
            "tags": cls.tags,
            "read_only": True,  # 默认值，实例化后才能准确判断
            "concurrency_safe": True,
            "requires_sandbox": cls.requires_sandbox,
            "input_schema": cls.input_schema.model_json_schema(),
        }
