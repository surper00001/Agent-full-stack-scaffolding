"""
Agent 基类 — Plan + ReAct 双模型架构。

支持：
- 独立的 Plan Model（推理/规划专用）和 Execute Model（执行/工具调用专用）
- 上下文窗口管理（ContextManager）
- 持久化检查点（SqliteSaver）
- Token 用量追踪
- 流式/非流式执行
- 工具注册表注入
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph
else:
    BaseChatModel = object
    CompiledStateGraph = object

from langchain_core.messages import BaseMessage, HumanMessage

from src.agents.checkpointer import get_checkpointer
from src.agents.context_manager import (
    ContextConfig,
    ContextManager,
    ContextUsage,
    TokenCounter,
    create_context_manager_from_settings,
)
from src.agents.graph import AgentGraphBuilder
from src.agents.tools import get_default_tools, get_tool_registry
from src.core.config import get_settings
from src.llm.callbacks import TokenUsageCallback
from src.monitoring.metrics import get_metrics
from src.monitoring.tracer import get_monitor


class BaseAgent:
    """Agent 基类 — 封装 Plan+ReAct 图执行与上下文管理。"""

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[Any] | None = None,
        system_prompt: str | None = None,
        tenant_id: str = "default",
        context_config: ContextConfig | None = None,
        vector_store: Any | None = None,
        plan_llm: BaseChatModel | None = None,
        enable_planning: bool = True,
    ) -> None:
        self._llm = llm
        self._plan_llm = plan_llm or llm  # 未指定则复用执行模型
        self._tools = tools or get_default_tools()
        self._system_prompt = system_prompt or "你是一个专业的视频创作 AI 助手，请根据用户需求提供专业帮助。"
        self._tenant_id = tenant_id
        self._enable_planning = enable_planning
        self._callback = TokenUsageCallback()
        self._settings = get_settings()

        # Context manager
        self._token_counter = TokenCounter(
            model_name=getattr(llm, "model_name", "default")
        )
        self._context_manager = create_context_manager_from_settings(
            llm=llm, vector_store=vector_store
        )
        if context_config:
            self._context_manager = ContextManager(
                config=context_config,
                token_counter=self._token_counter,
                summarizer=self._context_manager._summarizer,
                vector_store=vector_store,
            )

        self._last_context_stats: ContextUsage | None = None

        # Checkpointer
        self._checkpointer = self._init_checkpointer()

        # Build graph
        self._graph: CompiledStateGraph = self._build_graph()

        # 工具注册表（供外部查询）
        self._tool_registry = get_tool_registry()

    def _init_checkpointer(self) -> Any:
        return get_checkpointer()

    def _build_graph(self) -> CompiledStateGraph:
        builder = AgentGraphBuilder(
            plan_llm=self._plan_llm,
            execute_llm=self._llm,
            tools=self._tools,
        )
        builder.with_system_prompt(self._system_prompt)
        builder.with_checkpointer(self._checkpointer)
        builder.with_planning(self._enable_planning)
        builder.MAX_ITERATIONS = self._settings.agent_max_iterations
        return builder.build()

    async def run(
        self,
        user_input: str,
        chat_history: list[BaseMessage] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """非流式执行 Agent。"""
        monitor = get_monitor()
        metrics = get_metrics()
        metrics.increment("agent_executions")

        raw_history = list(chat_history or [])
        optimized = await self._context_manager.prepare_context(
            messages=raw_history,
            system_prompt=self._system_prompt,
        )
        self._last_context_stats = self._context_manager.stats

        messages = list(optimized)
        messages.append(HumanMessage(content=user_input))

        merged_meta: dict[str, Any] = dict(metadata or {})
        merged_meta["context_strategy"] = (
            self._context_manager.stats.strategy if self._context_manager.stats else ""
        )

        initial_state = {
            "messages": messages,
            "plan": [],
            "plan_summary": "",
            "current_step": 0,
            "iteration_count": 0,
            "tenant_id": self._tenant_id,
            "metadata": merged_meta,
        }

        try:
            with monitor.trace("agent_run", merged_meta):
                thread_id = (metadata or {}).get("thread_id", "default-thread")
                result = await self._graph.ainvoke(
                    initial_state,
                    config={
                        "callbacks": [self._callback],
                        "configurable": {
                            "tenant_id": self._tenant_id,
                            "thread_id": thread_id,
                        },
                    },
                )

            metrics.increment("agent_success")
            ctx = self._last_context_stats
            return {
                "messages": result.get("messages", []),
                "plan": result.get("plan", []),
                "plan_summary": result.get("plan_summary", ""),
                "token_usage": self._callback.get_summary(),
                "context_usage": {
                    "used_tokens": ctx.used_tokens if ctx else 0,
                    "max_tokens": ctx.available_tokens if ctx else 0,
                    "strategy": ctx.strategy if ctx else "",
                    "compressed_ratio": ctx.compressed_ratio if ctx else 0,
                    "has_summary": ctx.has_summary if ctx else False,
                },
                "metadata": result.get("metadata", {}),
            }

        except Exception:
            logger_import = __import__("loguru", fromlist=["logger"])
            logger_import.logger.error("Agent execution failed")
            raise

    async def stream(
        self,
        user_input: str,
        chat_history: list[BaseMessage] | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """流式执行 Agent，逐事件产出。"""
        raw_history = list(chat_history or [])
        optimized = await self._context_manager.prepare_context(
            messages=raw_history,
            system_prompt=self._system_prompt,
        )
        self._last_context_stats = self._context_manager.stats

        messages = list(optimized)
        messages.append(HumanMessage(content=user_input))

        merged_meta: dict[str, Any] = dict(metadata or {})
        thread_id = merged_meta.get("thread_id", "default-stream-thread")

        initial_state = {
            "messages": messages,
            "plan": [],
            "plan_summary": "",
            "current_step": 0,
            "iteration_count": 0,
            "tenant_id": self._tenant_id,
            "metadata": merged_meta,
        }

        async for event in self._graph.astream(
            initial_state,
            config={
                "callbacks": [self._callback],
                "configurable": {
                    "tenant_id": self._tenant_id,
                    "thread_id": thread_id,
                },
            },
        ):
            yield event

    def get_token_usage(self) -> dict[str, Any]:
        return self._callback.get_summary()

    @property
    def context_stats(self) -> ContextUsage | None:
        return self._last_context_stats

    @property
    def graph(self) -> CompiledStateGraph:
        return self._graph

    @property
    def tool_registry(self) -> dict[str, Any]:
        return self._tool_registry
