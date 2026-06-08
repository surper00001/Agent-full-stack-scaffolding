"""
Pipeline — 多阶段工具执行管道。

提供将多个工具调用串联为有序执行管道的抽象，
支持阶段间数据传递、条件分支和错误处理。

使用示例：
    pipeline = Pipeline("doc-ingest")
    pipeline.add_stage("parse", ParseStage())
    pipeline.add_stage("chunk", ChunkStage())
    result = await pipeline.run({"file_path": "/data/doc.pdf"})
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from loguru import logger


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StageResult:
    """单个阶段执行结果。"""
    stage_name: str
    status: StageStatus
    output: Any = None
    error: str | None = None
    duration_ms: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == StageStatus.COMPLETED


@dataclass
class PipelineResult:
    """管道执行完整结果。"""
    pipeline_name: str
    stages: list[StageResult] = field(default_factory=list)
    final_output: Any = None
    total_duration_ms: float = 0.0

    @property
    def success(self) -> bool:
        return all(s.status != StageStatus.FAILED for s in self.stages)

    @property
    def failed_stages(self) -> list[StageResult]:
        return [s for s in self.stages if s.status == StageStatus.FAILED]


class StageHandler(ABC):
    """管道阶段处理器基类。"""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> Any:
        """执行阶段逻辑，产出存入 context[name]。"""
        ...

    def on_error(self, error: Exception, context: dict[str, Any]) -> bool:
        """错误处理钩子。True=继续，False=终止管道。"""
        return False


class FunctionalStage(StageHandler):
    """将 async 函数包装为阶段处理器。"""

    def __init__(self, name: str, fn: Callable[..., Any], on_error_fn: Callable[..., bool] | None = None) -> None:
        super().__init__(name)
        self._fn = fn
        self._on_error_fn = on_error_fn

    async def execute(self, context: dict[str, Any]) -> Any:
        return await self._fn(context)

    def on_error(self, error: Exception, context: dict[str, Any]) -> bool:
        if self._on_error_fn:
            return self._on_error_fn(error, context)
        return False


class Pipeline:
    """多阶段执行管道。按序执行已注册的阶段，通过共享 context 传递数据。"""

    def __init__(self, name: str = "default") -> None:
        self._name = name
        self._stages: list[StageHandler] = []

    @property
    def name(self) -> str:
        return self._name

    def add_stage(self, name_or_handler: str | StageHandler, fn: Callable[..., Any] | None = None) -> Pipeline:
        """添加阶段。可传入 StageHandler 或 (name, fn) 快捷方式。"""
        if isinstance(name_or_handler, StageHandler):
            self._stages.append(name_or_handler)
        elif fn is not None:
            self._stages.append(FunctionalStage(name_or_handler, fn))
        return self

    async def run(self, initial_context: dict[str, Any] | None = None) -> PipelineResult:
        """按序执行所有阶段。"""
        context = dict(initial_context or {})
        results: list[StageResult] = []
        start = time.perf_counter()

        for handler in self._stages:
            stage_start = time.perf_counter()
            stage_result = StageResult(stage_name=handler.name, status=StageStatus.RUNNING)

            try:
                output = await handler.execute(context)
                context[handler.name] = output
                stage_result.status = StageStatus.COMPLETED
                stage_result.output = output
            except Exception as e:
                stage_result.status = StageStatus.FAILED
                stage_result.error = f"{type(e).__name__}: {e}"
                logger.warning(f"Pipeline [{self._name}] 阶段 [{handler.name}] 失败: {e}")
                if not handler.on_error(e, context):
                    stage_result.duration_ms = (time.perf_counter() - stage_start) * 1000
                    results.append(stage_result)
                    break

            stage_result.duration_ms = (time.perf_counter() - stage_start) * 1000
            results.append(stage_result)

        last = results[-1] if results else None
        return PipelineResult(
            pipeline_name=self._name,
            stages=results,
            final_output=context.get("_final") or (last.output if last else None),
            total_duration_ms=(time.perf_counter() - start) * 1000,
        )
