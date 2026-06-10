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

from src.core.config import get_settings
from src.monitoring.tracing import get_tracer

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
        self._planner_prompt: str | None = None  # None=使用默认 PLANNER_SYSTEM_PROMPT
        self._checkpointer: Any = MemorySaver()
        self._enable_planning: bool = True

    def with_system_prompt(self, prompt: str) -> AgentGraphBuilder:
        self._system_prompt = prompt
        return self

    def with_planner_prompt(self, prompt: str | None) -> AgentGraphBuilder:
        """设置 Planner 阶段的自定义提示词。None 则使用默认。"""
        self._planner_prompt = prompt
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
            tracer = get_tracer()
            with tracer.start_as_current_span("agent.planner") as span:
                span.set_attribute("agent.tools_count", len(self._tools))
                messages = state["messages"]
                user_content = ""
                for m in reversed(messages):
                    if isinstance(m, HumanMessage):
                        user_content = m.content if isinstance(m.content, str) else str(m.content)
                        break

                # 使用自定义 planner prompt（如果设置），否则使用默认
                planner_template = self._planner_prompt or PLANNER_SYSTEM_PROMPT

                # 构建工具列表摘要
                tool_lines = []
                for t in self._tools:
                    desc = (t.description or "").split("\n")[0][:120]
                    tool_lines.append(f"- **{t.name}**: {desc}")
                tool_summary = "\n".join(tool_lines) if tool_lines else "（无可用工具）"

                plan_prompt = planner_template.format(tool_list=tool_summary)
                plan_messages = [
                    SystemMessage(content=plan_prompt),
                    HumanMessage(content=f"用户需求：{user_content}\n\n请制定执行计划。"),
                ]

                try:
                    from src.llm.resilience import resilient_ainvoke

                    provider = get_settings().llm_provider
                    resp = await resilient_ainvoke(
                        plan_llm, plan_messages,
                        provider=f"{provider}/planner",
                        max_retries=2,  # 规划阶段快速失败
                    )
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
                        span.set_attribute("agent.plan_steps", len(plan))
                    else:
                        plan = []
                        plan_summary = "（计划生成失败，将直接执行）"
                        span.set_attribute("agent.plan_error", "no_json_found")
                except Exception as e:
                    logger.warning(f"Plan 生成失败: {e}")
                    plan = []
                    plan_summary = "（计划生成异常，将直接执行）"
                    span.set_attribute("agent.plan_error", str(e)[:200])

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
            tracer = get_tracer()
            with tracer.start_as_current_span("agent.executor") as span:
                messages = state["messages"]
                iteration = state.get("iteration_count", 0)
                plan = state.get("plan", [])
                plan_summary = state.get("plan_summary", "")
                current_step = state.get("current_step", 0)

                span.set_attribute("agent.iteration", iteration)
                span.set_attribute("agent.current_step", current_step)
                span.set_attribute("agent.plan_steps_total", len(plan))

                if iteration >= self.MAX_ITERATIONS:
                    span.set_attribute("agent.max_iterations_reached", True)
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

                from src.llm.resilience import resilient_ainvoke

                provider = get_settings().llm_provider
                response = await resilient_ainvoke(
                    llm, messages,
                    provider=f"{provider}/executor",
                    max_retries=3,
                )

                # 如果 response 没有 tool_calls 且还有后续步骤，推进步骤
                next_step = current_step
                has_tool_calls = (
                    isinstance(response, AIMessage)
                    and response.tool_calls
                    and len(response.tool_calls) > 0
                )
                if not has_tool_calls and plan and current_step < len(plan):
                    next_step = current_step + 1

                span.set_attribute("agent.has_tool_calls", has_tool_calls)
                span.set_attribute("agent.next_step", next_step)

                return {
                    "messages": [response],
                    "iteration_count": iteration + 1,
                    "current_step": next_step,
                }

        return executor_node

    # ---- Tool Node (StreamingToolExecutor 统一调度) ----

    def _make_tool_node(self):
        """构建工具执行节点。

        使用 StreamingToolExecutor 统一调度所有工具调用：
        - AbortSignal 树：一个工具失败可取消同级
        - 自动超时管理（默认 120s）
        - 只读工具并行，写工具互斥，非并发安全独占
        - HarnessTool 优先（权限检查 + 信号传播），LangChain 降级适配
        """
        from src.harness.abort_signal import AbortSignal
        from src.harness.streaming_executor import StreamingToolExecutor
        from src.harness.tool_registry import get_tool as get_harness_tool

        # 构建工具名 → LangChain 工具映射
        tool_map: dict[str, Any] = {t.name: t for t in self._tools}

        async def tool_node(state: AgentState) -> dict[str, Any]:
            tracer = get_tracer()
            with tracer.start_as_current_span("agent.tools") as span:
                messages = state["messages"]
                last_message = messages[-1]

                if not (isinstance(last_message, AIMessage) and last_message.tool_calls):
                    return {"messages": []}

                tool_calls = last_message.tool_calls
                if not tool_calls:
                    return {"messages": []}

                # 创建执行器（带 AbortSignal 树 — 父取消传播到所有子任务）
                root_signal = AbortSignal(name="tool-node")
                executor = StreamingToolExecutor(
                    abort_signal=root_signal,
                    max_parallel=8,
                    default_timeout_seconds=120.0,
                )

                # ── 提交所有工具调用，记录顺序 ──
                # 同名工具多次调用时，用 FIFO 队列处理
                name_call_id_map: dict[str, list[str]] = {}  # tool_name → [call_id1, call_id2, ...]
                unknown_results: dict[str, ToolMessage] = {}  # call_id → ToolMessage
                submitted_names: list[str] = []  # 保持提交顺序

                for tc in tool_calls:
                    tool_name: str = tc.get("name", "")
                    tool_args: dict[str, object] = tc.get("args", {})
                    tc_id: str = tc.get("id", "")
                    submitted_names.append(tool_name)

                    harness_tool = get_harness_tool(tool_name)
                    lc_tool = tool_map.get(tool_name)

                    if harness_tool is not None:
                        executor.submit(tool_name, tool_args)
                        name_call_id_map.setdefault(tool_name, []).append(tc_id)
                    elif lc_tool is not None:
                        executor.submit_raw(
                            tool_name=tool_name,
                            tool_args=tool_args,
                            execute_fn=lc_tool.ainvoke,
                            is_read_only=False,
                            is_concurrency_safe=False,
                        )
                        name_call_id_map.setdefault(tool_name, []).append(tc_id)
                    else:
                        unknown_results[tc_id] = ToolMessage(
                            content=(
                                f"工具 '{tool_name}' 未找到。"
                                f"可用工具: {', '.join(tool_map.keys())}。"
                                f"提示：使用 tool_search 查询可用工具。"
                            ),
                            tool_call_id=tc_id,
                            name=tool_name,
                        )
                        logger.warning(f"未知工具调用: {tool_name}")

                executor.mark_all_submitted()

                # ── 等待所有结果 ──
                all_results = await executor.wait_all()

                # Set span attributes for tool execution results
                span.set_attribute("agent.tools_submitted", len(tool_calls))
                span.set_attribute("agent.tools_succeeded", sum(1 for r in all_results if r.success))
                span.set_attribute("agent.tools_failed", sum(1 for r in all_results if not r.success))
                span.set_attribute("agent.tools_unknown", len(unknown_results))

                # ── 按原始调用顺序匹配结果到 tool_call_id ──
                # 构建 name → [results_queue]（FIFO）
                name_result_queues: dict[str, list[Any]] = {}
                for r in all_results:
                    name_result_queues.setdefault(r.tool_name, []).append(r)

                call_results: dict[str, ToolMessage] = dict(unknown_results)
                for tc in tool_calls:
                    tc_id = tc.get("id", "")
                    tool_name = tc.get("name", "")
                    if tc_id in call_results:
                        continue  # 已处理（未知工具）

                    queue = name_result_queues.get(tool_name, [])
                    if queue:
                        r = queue.pop(0)  # FIFO 消费
                        if r.success:
                            content = str(r.output) if not isinstance(r.output, str) else r.output
                        else:
                            content = f"[工具执行失败] {r.error}"
                        call_results[tc_id] = ToolMessage(
                            content=content,
                            tool_call_id=tc_id,
                            name=tool_name,
                        )

                # ── 保持原始调用顺序返回 ──
                ordered = [
                    call_results[tc.get("id", "")]
                    for tc in tool_calls
                    if tc.get("id", "") in call_results
                ]
                return {"messages": ordered}

        return tool_node

    # ---- 路由 ----

    @staticmethod
    def _should_continue(state: AgentState) -> Literal["continue", "end"]:
        messages = state["messages"]
        last_message = messages[-1]

        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            return "continue"
        return "end"


# ── Tool Node 辅助函数 ──

async def _invoke_tool(tool_call: dict, tool_map: dict[str, Any]) -> Any:
    """调用单个工具，返回原始结果或异常对象。"""
    from src.harness.tool_registry import get_tool as get_harness_tool

    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})

    # 优先走 HarnessTool（支持权限检查、AbortSignal）
    harness_tool = get_harness_tool(tool_name)
    if harness_tool is not None:
        try:
            from src.harness.abort_signal import AbortSignal

            input_obj = harness_tool.input_schema(**tool_args)

            # 权限检查
            perm = harness_tool.check_permissions(input_obj)
            if not perm.allowed:
                return f"[权限拒绝] {perm.reason}"

            signal = AbortSignal(name=f"agent-{tool_name}")
            result = await harness_tool.execute(input_obj, signal)
            return harness_tool.render_result(result)
        except Exception as e:
            return f"工具执行异常: {type(e).__name__}: {e}"

    # 降级到 LangChain tool
    lc_tool = tool_map.get(tool_name)
    if lc_tool is not None:
        try:
            output = await lc_tool.ainvoke(tool_args)
            result_text = str(output) if not isinstance(output, str) else output
            if result_text.startswith(("搜索失败:", "博查搜索 API Key")) or (
                "超时，请稍后重试" in result_text
            ):
                logger.warning(f"工具 {tool_name} 业务失败: {result_text[:160]}")
            else:
                logger.info(f"工具 {tool_name} 执行成功")
            return result_text
        except Exception as e:
            logger.error(f"工具 {tool_name} 执行失败: {e}")
            return f"工具执行异常: {e}"

    return None


def _to_tool_message(tool_call: dict, result: Any) -> ToolMessage:
    """将工具调用结果转换为 ToolMessage。"""
    tool_name = tool_call.get("name", "")
    tool_id = tool_call.get("id", "")

    if isinstance(result, Exception):
        result_text = f"工具执行异常: {type(result).__name__}: {result}"
    else:
        result_text = str(result) if not isinstance(result, str) else result

    return ToolMessage(content=result_text, tool_call_id=tool_id, name=tool_name)


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
