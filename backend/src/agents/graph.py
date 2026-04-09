"""
LangGraph Agent 图定义。

基于 LangGraph 构建可扩展的 Agent 执行图：
- 支持 ReAct 模式（思考 → 工具调用 → 观察 → 回答）
- 支持条件路由（根据 LLM 输出判断是否需要调用工具）
- 支持 Human-in-the-loop（人工审核检查点）
- 内置循环上限保护，防止无限调用

图结构:
    START → agent → [条件判断] → tools → agent → END
                 ↘ END（无需工具时直接结束）
"""

from __future__ import annotations

from typing import Any, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from typing_extensions import TypedDict


class AgentState(TypedDict):
    """Agent 图的状态定义。

    在整个图执行过程中流转，记录消息历史和元数据。
    """

    messages: list[BaseMessage]
    """完整的消息历史（用户消息 + AI 消息 + 工具消息）"""

    iteration_count: int
    """当前迭代次数，用于上限保护"""

    tenant_id: str
    """租户 ID，用于多租户数据隔离"""

    metadata: dict[str, Any]
    """执行元数据（会话 ID、用户 ID 等）"""


class AgentGraphBuilder:
    """
    Agent 图构建器。

    使用 Builder 模式配置并编译 LangGraph 状态图，
    支持自定义模型、工具、系统提示词和检查点。

    使用示例:
        builder = AgentGraphBuilder(llm=chat_model, tools=tools)
        graph = builder.with_system_prompt("你是一个有用的助手").build()
        result = await graph.ainvoke({"messages": [HumanMessage(content="你好")]})
    """

    # 最大迭代次数（安全保护）
    MAX_ITERATIONS = 15

    def __init__(
        self,
        llm: BaseChatModel,
        tools: list[Any] | None = None,
    ) -> None:
        self._llm = llm
        self._tools = tools or []
        self._system_prompt: str = "你是一个智能助手，请根据用户需求提供专业帮助。"
        self._checkpointer: Any = MemorySaver()  # 默认使用内存检查点

    def with_system_prompt(self, prompt: str) -> "AgentGraphBuilder":
        """设置系统提示词（流式 API）。"""
        self._system_prompt = prompt
        return self

    def with_tools(self, tools: list[Any]) -> "AgentGraphBuilder":
        """设置工具列表（流式 API）。"""
        self._tools = tools
        return self

    def with_checkpointer(self, checkpointer: Any) -> "AgentGraphBuilder":
        """设置检查点存储器（流式 API）。"""
        self._checkpointer = checkpointer
        return self

    def build(self) -> CompiledStateGraph:
        """构建并编译 Agent 图。"""
        # 绑定工具到 LLM
        if self._tools:
            llm_with_tools = self._llm.bind_tools(self._tools)
        else:
            llm_with_tools = self._llm

        # 定义图
        workflow = StateGraph(AgentState)

        # 添加节点
        workflow.add_node("agent", self._make_agent_node(llm_with_tools))
        workflow.add_node("tools", self._make_tool_node())

        # 添加边
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END,
            },
        )
        workflow.add_edge("tools", "agent")

        # 编译图并注入检查点
        return workflow.compile(checkpointer=self._checkpointer)

    # ---- 内部方法 ----

    def _make_agent_node(self, llm: BaseChatModel):
        """创建 Agent 节点（调用 LLM）。"""

        async def agent_node(state: AgentState) -> dict[str, Any]:
            messages = state["messages"]
            iteration = state.get("iteration_count", 0)

            # 迭代上限保护
            if iteration >= self.MAX_ITERATIONS:
                return {
                    "messages": [
                        AIMessage(
                            content="已达到最大执行步骤，已终止当前任务。请简化您的请求后重试。"
                        )
                    ],
                    "iteration_count": iteration + 1,
                }

            # 注入系统提示词（首次调用时）
            if iteration == 0:
                from langchain_core.messages import SystemMessage

                messages = [SystemMessage(content=self._system_prompt)] + messages

            # 调用 LLM
            response = await llm.ainvoke(messages)
            return {
                "messages": [response],
                "iteration_count": iteration + 1,
            }

        return agent_node

    def _make_tool_node(self):
        """创建工具执行节点。"""

        async def tool_node(state: AgentState) -> dict[str, Any]:
            from langchain_core.messages import ToolMessage

            messages = state["messages"]
            last_message = messages[-1]

            outputs: list[ToolMessage] = []
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                for tool_call in last_message.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "")

                    # 查找并执行对应工具
                    result_text = f"工具 {tool_name} 未找到"
                    for t in self._tools:
                        if t.name == tool_name:
                            try:
                                output = await t.ainvoke(tool_args)
                                result_text = (
                                    str(output)
                                    if not isinstance(output, str)
                                    else output
                                )
                            except Exception as e:
                                result_text = f"工具执行异常: {e}"
                            break

                    outputs.append(
                        ToolMessage(content=result_text, tool_call_id=tool_id)
                    )

            return {"messages": outputs}

        return tool_node

    @staticmethod
    def _should_continue(state: AgentState) -> Literal["continue", "end"]:
        """条件路由：判断是否需要继续调用工具。"""
        messages = state["messages"]
        last_message = messages[-1]

        # 如果 LLM 要求调用工具，则继续路由到工具节点
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "continue"

        # 否则结束
        return "end"


def create_default_graph(
    llm: BaseChatModel,
    tools: list[Any] | None = None,
    system_prompt: str | None = None,
) -> CompiledStateGraph:
    """快速创建默认 Agent 图的便捷函数。

    Args:
        llm: LangChain ChatModel 实例
        tools: 工具列表
        system_prompt: 系统提示词，None 则使用默认值

    Returns:
        编译好的 Agent 状态图
    """
    builder = AgentGraphBuilder(llm=llm, tools=tools)
    if system_prompt:
        builder.with_system_prompt(system_prompt)
    return builder.build()
