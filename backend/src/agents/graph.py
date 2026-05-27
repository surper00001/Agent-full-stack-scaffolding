"""
LangGraph Agent 图定义 — Plan + ReAct 双阶段架构。

图结构:
    START → planner → executor → [condition] → tools → executor
                         ↘ END

Planner:  使用 Plan Model（可独立选型）分析需求，输出结构化执行计划
Executor: ReAct 循环，根据 Plan 逐步执行，调用工具完成创作任务
Tools:    支持 tool_search 元工具做动态工具发现
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph, add_messages
from loguru import logger
from typing_extensions import TypedDict

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph


class PlanStep(TypedDict, total=False):
    """单个执行步骤。"""
    step: int
    action: str          # 描述这一步做什么
    tool: str            # 建议使用的工具名，空字符串表示纯 LLM 推理
    expected_output: str # 预期产出


class AgentState(TypedDict):
    """Agent 图状态 — Plan + ReAct 双阶段。"""

    messages: Annotated[list[BaseMessage], add_messages]
    """完整消息历史（add_messages reducer 保证追加而非覆盖）"""

    plan: list[PlanStep]
    """Planner 输出的执行计划"""

    plan_summary: str
    """计划摘要，注入 executor 的 system prompt"""

    current_step: int
    """当前执行的计划步骤序号（从 0 开始）"""

    iteration_count: int
    """当前迭代次数，防止死循环"""

    tenant_id: str
    """租户 ID"""

    metadata: dict[str, Any]
    """执行元数据"""


# ---- Plan 生成提示词 ----

PLANNER_SYSTEM_PROMPT = """你是一位资深的视频创作策划专家。分析用户的创作需求，制定一个高效的执行计划。

## 可用工具速查
{tool_list}

## 输出格式
你必须输出一个 JSON 数组作为执行计划，每个元素包含：
- step: 步骤序号（从1开始）
- action: 这一步要完成什么（用中文描述）
- tool: 建议使用的工具名（从上述工具列表中选择，纯 LLM 推理则填 ""）
- expected_output: 这一步的预期产出

## 计划原则
1. 搜索/调研类工具优先使用，获取最新信息
2. 创作类工具按逻辑顺序排列（脚本→分镜→拍摄清单）
3. 最终输出必须使用文件保存工具（save_markdown_file / save_text_file）
4. 步骤 3-7 个为宜，不要过度拆分
5. 如果用户要求很简单（如计算、问答），步骤可以少

只输出 JSON 数组，不要其他内容。"""


class AgentGraphBuilder:
    """
    Plan + ReAct Agent 图构建器。

    使用示例:
        builder = AgentGraphBuilder(
            plan_llm=reasoning_model,
            execute_llm=chat_model,
            tools=tools,
        )
        graph = builder.with_system_prompt("你是视频创作专家").build()
    """

    MAX_ITERATIONS = 15

    def __init__(
        self,
        plan_llm: BaseChatModel | None = None,
        execute_llm: BaseChatModel | None = None,
        tools: list[Any] | None = None,
    ) -> None:
        # Plan 模型：如果未单独指定，复用 execute_llm
        if plan_llm is None and execute_llm is None:
            raise ValueError("plan_llm 和 execute_llm 至少需要提供一个")
        self._plan_llm = plan_llm or execute_llm
        self._execute_llm = execute_llm or plan_llm
        self._tools = tools or []
        self._system_prompt: str = "你是一个专业的视频创作 AI 助手。"
        self._checkpointer: Any = MemorySaver()
        self._enable_planning: bool = True

    def with_system_prompt(self, prompt: str) -> AgentGraphBuilder:
        self._system_prompt = prompt
        return self

    def with_tools(self, tools: list[Any]) -> AgentGraphBuilder:
        self._tools = tools
        return self

    def with_checkpointer(self, checkpointer: Any) -> AgentGraphBuilder:
        self._checkpointer = checkpointer
        return self

    def with_planning(self, enabled: bool) -> AgentGraphBuilder:
        """启用/禁用规划阶段。简单对话可禁用。"""
        self._enable_planning = enabled
        return self

    def build(self) -> CompiledStateGraph:
        """构建 Plan + ReAct 图。"""
        execute_llm_with_tools = self._execute_llm.bind_tools(self._tools) if self._tools else self._execute_llm

        workflow = StateGraph(AgentState)

        if self._enable_planning:
            workflow.add_node("planner", self._make_planner_node())
            workflow.add_node("executor", self._make_executor_node(execute_llm_with_tools))
            workflow.add_node("tools", self._make_tool_node())

            workflow.add_edge(START, "planner")
            workflow.add_edge("planner", "executor")
            workflow.add_conditional_edges(
                "executor",
                self._should_continue,
                {"continue": "tools", "end": END},
            )
            workflow.add_edge("tools", "executor")
        else:
            # 降级：纯 ReAct（无 Plan）
            workflow.add_node("executor", self._make_executor_node(execute_llm_with_tools))
            workflow.add_node("tools", self._make_tool_node())

            workflow.add_edge(START, "executor")
            workflow.add_conditional_edges(
                "executor",
                self._should_continue,
                {"continue": "tools", "end": END},
            )
            workflow.add_edge("tools", "executor")

        return workflow.compile(checkpointer=self._checkpointer)

    # ---- Planner Node ----

    def _make_planner_node(self):
        plan_llm = self._plan_llm

        async def planner_node(state: AgentState) -> dict[str, Any]:
            messages = state["messages"]
            user_content = ""
            for m in reversed(messages):
                if isinstance(m, HumanMessage):
                    user_content = m.content if isinstance(m.content, str) else str(m.content)
                    break

            # 构建工具列表摘要
            tool_lines = []
            for t in self._tools:
                desc = (t.description or "").split("\n")[0][:120]
                tool_lines.append(f"- **{t.name}**: {desc}")
            tool_summary = "\n".join(tool_lines) if tool_lines else "（无可用工具）"

            plan_prompt = PLANNER_SYSTEM_PROMPT.format(tool_list=tool_summary)
            plan_messages = [
                SystemMessage(content=plan_prompt),
                HumanMessage(content=f"用户需求：{user_content}\n\n请制定执行计划。"),
            ]

            try:
                resp = await plan_llm.ainvoke(plan_messages)
                plan_text = resp.content if isinstance(resp.content, str) else str(resp.content)

                # 解析 JSON 计划
                import re
                json_match = re.search(r"\[[\s\S]*\]", plan_text)
                if json_match:
                    plan_data = json_loads_strict(json_match.group())
                    plan: list[PlanStep] = [
                        PlanStep(
                            step=item.get("step", i + 1),
                            action=item.get("action", ""),
                            tool=item.get("tool", ""),
                            expected_output=item.get("expected_output", ""),
                        )
                        for i, item in enumerate(plan_data)
                    ]
                    plan_summary = "\n".join(
                        f"  {p['step']}. [{p['tool'] or 'LLM'}] {p['action']}"
                        for p in plan
                    )
                    logger.info(f"Plan 生成完成: {len(plan)} 步骤")
                else:
                    plan = []
                    plan_summary = "（计划生成失败，将直接执行）"
            except Exception as e:
                logger.warning(f"Plan 生成失败: {e}")
                plan = []
                plan_summary = "（计划生成异常，将直接执行）"

            return {
                "plan": plan,
                "plan_summary": plan_summary,
                "current_step": 0,
                "iteration_count": 0,
            }

        return planner_node

    # ---- Executor Node ----

    def _make_executor_node(self, llm: BaseChatModel):
        async def executor_node(state: AgentState) -> dict[str, Any]:
            messages = state["messages"]
            iteration = state.get("iteration_count", 0)
            plan = state.get("plan", [])
            plan_summary = state.get("plan_summary", "")
            current_step = state.get("current_step", 0)

            if iteration >= self.MAX_ITERATIONS:
                return {
                    "messages": [AIMessage(content="已达到最大执行步骤，已终止。请简化请求后重试。")],
                    "iteration_count": iteration + 1,
                }

            # 首次执行：注入 system prompt + plan
            if iteration == 0:
                has_system = any(isinstance(m, SystemMessage) for m in messages)

                if not has_system:
                    full_prompt = self._system_prompt
                    if plan_summary:
                        full_prompt += (
                            f"\n\n## 执行计划\n{plan_summary}\n\n"
                            "请按计划逐步执行。每一步完成后，如果涉及文件输出，"
                            "务必使用 save_markdown_file 或 save_text_file 保存结果。"
                            "如果你不确定该使用哪个工具，可以先调用 tool_search 查询。"
                        )
                    messages = [SystemMessage(content=full_prompt)] + messages

            # 当前步骤提示
            if plan and current_step < len(plan):
                step = plan[current_step]
                step_hint = HumanMessage(
                    content=f"【当前步骤 {step['step']}/{len(plan)}】{step['action']}"
                )
                messages = list(messages) + [step_hint]

            response = await llm.ainvoke(messages)

            # 如果 response 没有 tool_calls 且还有后续步骤，推进步骤
            next_step = current_step
            has_tool_calls = (
                isinstance(response, AIMessage)
                and response.tool_calls
                and len(response.tool_calls) > 0
            )
            if not has_tool_calls and plan and current_step < len(plan):
                next_step = current_step + 1

            return {
                "messages": [response],
                "iteration_count": iteration + 1,
                "current_step": next_step,
            }

        return executor_node

    # ---- Tool Node ----

    def _make_tool_node(self):
        # 构建工具名→工具对象的映射
        tool_map: dict[str, Any] = {t.name: t for t in self._tools}

        async def tool_node(state: AgentState) -> dict[str, Any]:
            messages = state["messages"]
            last_message = messages[-1]

            outputs: list[ToolMessage] = []
            if isinstance(last_message, AIMessage) and last_message.tool_calls:
                for tool_call in last_message.tool_calls:
                    tool_name = tool_call.get("name", "")
                    tool_args = tool_call.get("args", {})
                    tool_id = tool_call.get("id", "")

                    t = tool_map.get(tool_name)
                    if t is None:
                        result_text = (
                            f"工具 '{tool_name}' 未找到。"
                            f"可用工具: {', '.join(tool_map.keys())}。"
                            f"提示：使用 tool_search 查询可用工具。"
                        )
                        logger.warning(f"未知工具调用: {tool_name}")
                    else:
                        try:
                            output = await t.ainvoke(tool_args)
                            result_text = str(output) if not isinstance(output, str) else output
                            if result_text.startswith(("搜索失败:", "博查搜索 API Key")) or (
                                "超时，请稍后重试" in result_text
                            ):
                                logger.warning(
                                    f"工具 {tool_name} 业务失败: {result_text[:160]}"
                                )
                            else:
                                logger.info(f"工具 {tool_name} 执行成功")
                        except Exception as e:
                            result_text = f"工具执行异常: {e}"
                            logger.error(f"工具 {tool_name} 执行失败: {e}")

                    outputs.append(ToolMessage(
                        content=result_text,
                        tool_call_id=tool_id,
                        name=tool_name,
                    ))

            return {"messages": outputs}

        return tool_node

    # ---- 路由 ----

    @staticmethod
    def _should_continue(state: AgentState) -> Literal["continue", "end"]:
        messages = state["messages"]
        last_message = messages[-1]

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "continue"
        return "end"


def create_default_graph(
    llm: BaseChatModel,
    tools: list[Any] | None = None,
    system_prompt: str | None = None,
    plan_llm: BaseChatModel | None = None,
) -> CompiledStateGraph:
    """快速创建 Plan + ReAct Agent 图。

    Args:
        llm: 执行模型
        tools: 工具列表
        system_prompt: 系统提示词
        plan_llm: 规划模型（可选，默认复用 llm）
    """
    from src.core.config import get_settings

    builder = AgentGraphBuilder(
        plan_llm=plan_llm or llm,
        execute_llm=llm,
        tools=tools,
    )
    if system_prompt:
        builder.with_system_prompt(system_prompt)
    builder.MAX_ITERATIONS = get_settings().agent_max_iterations
    return builder.build()


def json_loads_strict(text: str) -> Any:
    """更宽松的 JSON 解析：尝试修复常见 LLM 输出问题。"""
    import json as _json
    import re

    text = text.strip()
    # 移除 Markdown 代码块标记
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # 移除尾部逗号
    text = re.sub(r",\s*([}\]])", r"\1", text)
    return _json.loads(text)
