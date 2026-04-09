"""
Agent 基类。

提供 Agent 生命周期管理（创建、运行、停止），
业务方继承此类可快速实现自定义 Agent。
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from src.agents.graph import create_default_graph
from src.agents.tools import get_default_tools
from src.llm.callbacks import TokenUsageCallback
from src.monitoring.metrics import get_metrics
from src.monitoring.tracer import get_monitor


class BaseAgent:
    """
    Agent 基类。

    封装 LangGraph 图的执行逻辑，统一处理：
    - 消息历史管理
    - Token 用量追踪
    - 错误处理
    - 指标上报

    子类可重写 _build_graph() 来实现自定义图结构。
    """

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[Any] | None = None,
        system_prompt: str | None = None,
        tenant_id: str = "default",
    ) -> None:
        self._llm = llm
        self._tools = tools or get_default_tools()
        self._system_prompt = system_prompt or "你是一个智能助手，请根据用户需求提供专业帮助。"
        self._tenant_id = tenant_id
        self._callback = TokenUsageCallback()

        # 构建编译后的图
        self._graph: CompiledStateGraph = self._build_graph()

    def _build_graph(self) -> CompiledStateGraph:
        """构建 LangGraph 执行图（子类可重写）。"""
        return create_default_graph(
            llm=self._llm,
            tools=self._tools,
            system_prompt=self._system_prompt,
        )

    async def run(
        self,
        user_input: str,
        chat_history: list[BaseMessage] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        执行 Agent 推理。

        Args:
            user_input: 用户输入文本
            chat_history: 历史消息列表（可选，用于多轮对话）
            metadata: 执行元数据（会话 ID 等）

        Returns:
            包含 messages、token_usage、metadata 的字典
        """
        monitor = get_monitor()
        metrics = get_metrics()
        metrics.increment("agent_executions")

        # 构建消息列表
        messages = list(chat_history or [])
        messages.append(HumanMessage(content=user_input))

        initial_state = {
            "messages": messages,
            "iteration_count": 0,
            "tenant_id": self._tenant_id,
            "metadata": metadata or {},
        }

        try:
            with monitor.trace("agent_run", metadata):
                # 调用 LangGraph 图执行
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
            return {
                "messages": result.get("messages", []),
                "token_usage": self._callback.get_summary(),
                "metadata": result.get("metadata", {}),
            }

        except Exception as e:
            from loguru import logger

            logger.error(f"Agent 执行失败: {e}")
            raise

    async def stream(
        self,
        user_input: str,
        chat_history: list[BaseMessage] | None = None,
    ):
        """
        流式执行 Agent 推理。

        Args:
            user_input: 用户输入文本
            chat_history: 历史消息列表

        Yields:
            Agent 每一步的输出事件
        """
        messages = list(chat_history or [])
        messages.append(HumanMessage(content=user_input))

        initial_state = {
            "messages": messages,
            "iteration_count": 0,
            "tenant_id": self._tenant_id,
            "metadata": {},
        }

        async for event in self._graph.astream(
            initial_state,
            config={
                "configurable": {
                    "tenant_id": self._tenant_id,
                    "thread_id": "default-stream-thread",
                }
            },
        ):
            yield event

    def get_token_usage(self) -> dict[str, Any]:
        """获取当前会话的 Token 用量统计。"""
        return self._callback.get_summary()

    @property
    def graph(self) -> CompiledStateGraph:
        """获取底层编译后的 LangGraph 图。"""
        return self._graph
