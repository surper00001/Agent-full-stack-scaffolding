"""
StreamingToolExecutor — 流式并行工具调度器。

核心思想：LLM 边输出 tool_call 边调度执行，不等 LLM 完整响应。

调度规则：
1. 只读工具之间可以并行
2. 非并发安全的工具独占执行
3. 非只读工具独占执行（读写操作互斥）
4. 结果按 LLM 调用顺序返回（保持语义一致性）
5. AbortSignal 树：用户取消 → 所有工具停止

与传统 ReAct 对比：
    传统：LLM完整输出 → T1→T2→T3 顺序执行 → LLM再次推理
    本系统：LLM边输出 → T1/T2并行(T3排队) → 结果顺序返回 → 实时反馈给LLM
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

from src.harness.abort_signal import AbortSignal
from src.harness.tool_base import HarnessTool, ToolResult


class ToolTaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ToolTask:
    """单个工具执行任务。"""
    id: str
    tool: HarnessTool
    input: Any  # Pydantic BaseModel
    status: ToolTaskStatus = ToolTaskStatus.QUEUED
    result: ToolResult | None = None
    is_read_only: bool = False
    is_concurrency_safe: bool = False
    abort_signal: AbortSignal | None = None
    created_at: float = field(default_factory=time.monotonic)
    started_at: float | None = None
    finished_at: float | None = None
    retries: int = 0
    max_retries: int = 2


class StreamingToolExecutor:
    """
    流式工具执行器。

    接收 LLM 流式产出的 tool_call，立即调度执行，
    结果按输入顺序返回给 LLM。

    使用方式：
        executor = StreamingToolExecutor(abort_signal=user_signal)

        # LLM 边输出边提交
        async for chunk in llm.stream(...):
            if chunk.is_tool_call:
                executor.submit_tool_call(chunk.tool_call)

        # 等待结果，实时产出
        async for result in executor.results():
            yield result

        # 或者等待全部完成
        all_results = await executor.wait_all()
    """

    def __init__(
        self,
        abort_signal: AbortSignal | None = None,
        max_parallel: int = 8,
        default_timeout_seconds: float = 60.0,
    ) -> None:
        self._abort_signal = abort_signal or AbortSignal(name="executor-root")
        self._max_parallel = max(1, min(max_parallel, 16))
        self._default_timeout = default_timeout_seconds

        # 任务存储
        self._queue: list[ToolTask] = []
        self._in_flight: set[str] = set()
        self._completed: list[ToolTask] = []
        self._task_map: dict[str, ToolTask] = {}

        # 同步
        self._completion_event = asyncio.Event()
        self._all_submitted = False

        # 统计
        self._submitted_count = 0
        self._completed_count = 0
        self._failed_count = 0
        self._cancelled_count = 0

    # ── 公共接口 ──

    def submit(self, tool_name: str, tool_input: Any) -> ToolTask | None:
        """
        提交工具调用任务。

        Args:
            tool_name: 工具名（对应 HarnessTool.name）
            tool_input: 工具输入（Pydantic BaseModel 实例或 dict）

        Returns:
            ToolTask 对象（可用于跟踪状态），如果工具被禁用返回 None
        """
        from src.harness.tool_registry import get_tool_registry
        registry = get_tool_registry()
        tool = registry.get(tool_name)
        if tool is None:
            logger.warning(f"工具 '{tool_name}' 未注册，跳过")
            return None

        if not tool.is_enabled():
            logger.warning(f"工具 '{tool_name}' 当前不可用，跳过")
            return None

        # 统一转为 Pydantic 实例
        if isinstance(tool_input, dict):
            input_obj = tool.input_schema(**tool_input)
        else:
            input_obj = tool_input

        # 业务校验
        validation = tool.validate_input(input_obj)
        if not validation.valid:
            logger.warning(f"工具 '{tool_name}' 输入校验失败: {validation.errors}")
            return None

        task_id = f"{tool_name}-{self._submitted_count}-{id(tool_input):x}"
        task = ToolTask(
            id=task_id,
            tool=tool,
            input=input_obj,
            is_read_only=tool.is_read_only(input_obj),
            is_concurrency_safe=tool.is_concurrency_safe(input_obj),
            abort_signal=self._abort_signal.create_child(f"task-{tool_name}"),
        )

        self._queue.append(task)
        self._task_map[task.id] = task
        self._submitted_count += 1

        # 尝试立即调度
        asyncio.create_task(self._try_schedule(task))

        return task

    def submit_all(self, tool_calls: list[tuple[str, Any]]) -> list[ToolTask]:
        """批量提交工具调用。"""
        tasks = []
        for name, input_data in tool_calls:
            task = self.submit(name, input_data)
            if task:
                tasks.append(task)
        self._all_submitted = True
        return tasks

    def mark_all_submitted(self) -> None:
        """标记所有任务已提交，results() 将正常退出。"""
        self._all_submitted = True

    async def results(self) -> AsyncGenerator[ToolResult, None]:
        """
        流式产出已完成的任务结果。

        保持与 submit 相同的顺序。调用方可以边等待边处理。
        """
        yielded = 0
        while True:
            # 产出已完成但未产出的结果
            while self._completed:
                # 找到下一个按序的结果
                task = self._completed.pop(0)
                if task.status == ToolTaskStatus.DONE and task.result:
                    yielded += 1
                    yield task.result
                elif task.status == ToolTaskStatus.FAILED:
                    yielded += 1
                    yield ToolResult.fail(
                        name=task.tool.name,
                        error=task.result.error if task.result else "未知错误",
                    )
                elif task.status == ToolTaskStatus.CANCELLED:
                    yielded += 1
                    yield ToolResult.fail(
                        name=task.tool.name,
                        error="任务已取消",
                    )

            # 检查是否全部完成
            if self._all_submitted and len(self._in_flight) == 0 and not self._queue:
                break

            # 等待新结果
            self._completion_event.clear()
            await asyncio.wait_for(
                self._completion_event.wait(),
                timeout=5.0,  # 5秒心跳
            )

    async def wait_all(self) -> list[ToolResult]:
        """等待所有任务完成，返回结果列表。"""
        results = []
        async for result in self.results():
            results.append(result)
        return results

    # ── 调度核心 ──

    async def _try_schedule(self, task: ToolTask) -> None:
        """尝试调度一个任务，检查并发约束。"""
        if task.status != ToolTaskStatus.QUEUED:
            return

        # 并发限制
        if len(self._in_flight) >= self._max_parallel:
            return  # 等有空位

        # 检查：有无独占工具在执行？
        has_exclusive_running = False
        for tid in self._in_flight:
            t = self._task_map.get(tid)
            if t and not t.is_concurrency_safe:
                has_exclusive_running = True
                break

        if has_exclusive_running and not task.is_concurrency_safe:
            return  # 排队等待独占任务完成

        # 检查：非只读工具只能独占
        if not task.is_read_only and len(self._in_flight) > 0:
            return  # 读写操作互斥

        # 通过检查，开始执行
        self._queue.remove(task)
        await self._execute_task(task)

    async def _execute_task(self, task: ToolTask) -> None:
        """执行单个任务。"""
        task.status = ToolTaskStatus.RUNNING
        task.started_at = time.monotonic()
        self._in_flight.add(task.id)

        try:
            # 权限检查
            perm = task.tool.check_permissions(task.input)
            if not perm.allowed:
                if perm.requires_approval:
                    # 需要审批 — 这里先拒绝，后续集成审批流
                    task.result = ToolResult.fail(
                        name=task.tool.name,
                        error=f"需要人工审批: {perm.reason}",
                        requires_approval=True,
                    )
                    task.status = ToolTaskStatus.FAILED
                    self._failed_count += 1
                    return
                else:
                    task.result = ToolResult.fail(
                        name=task.tool.name,
                        error=f"权限不足: {perm.reason}",
                    )
                    task.status = ToolTaskStatus.FAILED
                    self._failed_count += 1
                    return

            # 执行工具
            start = time.perf_counter()
            try:
                output = await asyncio.wait_for(
                    task.tool.execute(task.input, task.abort_signal),
                    timeout=self._default_timeout,
                )
                elapsed = (time.perf_counter() - start) * 1000
                task.result = ToolResult.ok(
                    name=task.tool.name,
                    output=output,
                    duration_ms=elapsed,
                )
                task.status = ToolTaskStatus.DONE
                self._completed_count += 1
            except TimeoutError:
                task.abort_signal.abort("执行超时")
                task.result = ToolResult.fail(
                    name=task.tool.name,
                    error=f"执行超时（{self._default_timeout}s）",
                )
                task.status = ToolTaskStatus.FAILED
                self._failed_count += 1
            except Exception as e:
                task.result = ToolResult.fail(
                    name=task.tool.name,
                    error=f"{type(e).__name__}: {e}",
                )
                task.status = ToolTaskStatus.FAILED
                self._failed_count += 1

        finally:
            task.finished_at = time.monotonic()
            self._in_flight.discard(task.id)
            self._completed.append(task)
            self._completion_event.set()

            # 尝试调度排队的任务
            for queued in list(self._queue):
                await self._try_schedule(queued)

    # ── 取消 ──

    def cancel_all(self, reason: str = "用户取消") -> None:
        """取消所有任务。"""
        self._abort_signal.abort(reason)
        for task in self._queue:
            task.status = ToolTaskStatus.CANCELLED
            self._cancelled_count += 1
        self._queue.clear()
        self._all_submitted = True
        self._completion_event.set()

    # ── 统计 ──

    @property
    def pending_count(self) -> int:
        return len(self._queue)

    @property
    def running_count(self) -> int:
        return len(self._in_flight)

    @property
    def stats(self) -> dict[str, int]:
        return {
            "submitted": self._submitted_count,
            "completed": self._completed_count,
            "failed": self._failed_count,
            "cancelled": self._cancelled_count,
            "in_flight": len(self._in_flight),
            "queued": len(self._queue),
        }
