"""
Agent LangGraph 图结构测试。

验证图构建和基本执行逻辑。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage

from src.agents.graph import AgentGraphBuilder
from src.agents.tools import get_default_tools


@pytest.fixture
def mock_llm() -> AsyncMock:
    """创建 Mock LLM，返回预定义的 AI 消息。"""
    llm = AsyncMock()
    # 模拟返回：不带 tool_calls 的普通 AI 消息（直接结束）
    from langchain_core.messages import AIMessage

    llm.bind_tools = MagicMock(return_value=llm)
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="你好！有什么可以帮你的？")
    )
    return llm


@pytest.mark.asyncio
@pytest.mark.unit
async def test_build_graph(mock_llm: AsyncMock) -> None:
    """测试图构建成功。"""
    tools = get_default_tools()
    builder = AgentGraphBuilder(execute_llm=mock_llm, tools=tools)
    graph = builder.build()

    assert graph is not None
    # 验证图中有 agent 和 tools 两个节点
    nodes = graph.get_graph().nodes
    assert "executor" in nodes
    assert "tools" in nodes


@pytest.mark.asyncio
@pytest.mark.unit
async def test_graph_invoke_basic(mock_llm: AsyncMock) -> None:
    """测试图基本调用（无需工具的场景）。"""
    tools = get_default_tools()
    builder = AgentGraphBuilder(execute_llm=mock_llm, tools=tools)
    graph = builder.with_system_prompt("你是一个客服助手").build()

    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="你好")],
            "iteration_count": 0,
            "tenant_id": "test",
            "metadata": {},
        },
        config={"configurable": {"thread_id": "test-thread-1"}},
    )

    assert "messages" in result
    assert len(result["messages"]) > 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_max_iterations_protection(mock_llm: AsyncMock) -> None:
    """测试迭代上限保护。"""
    from langchain_core.messages import AIMessage

    # 模拟一直返回 tool_calls（会触发循环）
    mock_llm.ainvoke = AsyncMock(
        return_value=AIMessage(
            content="调用工具",
            tool_calls=[{"name": "calculator", "args": {"expression": "1+1"}, "id": "1"}],
        )
    )

    builder = AgentGraphBuilder(execute_llm=mock_llm, tools=get_default_tools())
    builder._enable_planning = False  # 跳过 planner，直接测 executor 的迭代上限
    graph = builder.build()

    result = await graph.ainvoke(
        {
            "messages": [HumanMessage(content="计算 1+1")],
            "iteration_count": AgentGraphBuilder.MAX_ITERATIONS,
            "tenant_id": "test",
            "metadata": {},
        },
        config={"configurable": {"thread_id": "test-thread-2"}},
    )

    final_msg = result["messages"][-1]
    assert "已达到最大执行步骤" in final_msg.content


@pytest.mark.asyncio
@pytest.mark.unit
async def test_agent_state_structure() -> None:
    """测试 AgentState 类型结构完整。"""
    from src.agents.graph import AgentState

    state: AgentState = {
        "messages": [HumanMessage(content="测试")],
        "iteration_count": 0,
        "tenant_id": "default",
        "metadata": {"session_id": "123"},
    }
    assert state["iteration_count"] == 0
    assert state["tenant_id"] == "default"
    assert state["metadata"]["session_id"] == "123"
