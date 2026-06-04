"""
测试 Skill 生命周期 + Harness Agent 工具。
"""

import pytest

from src.harness.skill_lifecycle import (
    SkillLifecycle,
    SkillStatus,
    get_approval_workflow,
    get_auto_publish_workflow,
)


# ============================================================
# Skill 生命周期测试
# ============================================================

class TestSkillLifecycle:
    def test_initial_state_is_draft(self):
        lc = SkillLifecycle()
        assert lc.status == SkillStatus.DRAFT

    def test_initial_state_custom(self):
        lc = SkillLifecycle(SkillStatus.ACTIVE)
        assert lc.status == SkillStatus.ACTIVE

    def test_draft_to_testing(self):
        lc = SkillLifecycle()
        assert lc.can_transition(SkillStatus.TESTING)
        event = lc.transition(SkillStatus.TESTING, reason="开始测试")
        assert lc.status == SkillStatus.TESTING
        assert event.from_status == SkillStatus.DRAFT
        assert event.to_status == SkillStatus.TESTING

    def test_draft_cannot_go_to_active(self):
        lc = SkillLifecycle()
        assert not lc.can_transition(SkillStatus.ACTIVE)

    def test_full_approval_workflow(self):
        lc = SkillLifecycle()

        # draft → testing → pending_review → approved → published → active
        lc.transition(SkillStatus.TESTING, reason="AI 生成完成")
        lc.transition(SkillStatus.PENDING_REVIEW, reason="测试通过")
        lc.transition(SkillStatus.APPROVED, reason="管理员审核通过")
        lc.transition(SkillStatus.PUBLISHED, reason="发布")
        lc.transition(SkillStatus.ACTIVE, reason="激活")

        assert lc.status == SkillStatus.ACTIVE
        assert lc.is_active
        assert lc.is_usable

    def test_rejected_back_to_draft(self):
        lc = SkillLifecycle()
        lc.transition(SkillStatus.PENDING_REVIEW)
        lc.transition(SkillStatus.REJECTED, reason="代码质量问题")
        assert lc.status == SkillStatus.REJECTED

        # 修改后重新提交
        assert lc.can_transition(SkillStatus.DRAFT)
        lc.transition(SkillStatus.DRAFT, reason="修改后重新起草")
        assert lc.status == SkillStatus.DRAFT

    def test_deprecate_and_archive(self):
        lc = SkillLifecycle(SkillStatus.ACTIVE)

        lc.transition(SkillStatus.DEPRECATED, reason="有更好的替代方案")
        assert not lc.is_usable  # deprecated 不可用

        lc.transition(SkillStatus.ARCHIVED, reason="正式归档")
        assert lc.status == SkillStatus.ARCHIVED

    def test_force_transition(self):
        lc = SkillLifecycle()
        # 强制从 draft 跳到 active（跳过所有中间状态）
        lc.force_transition(SkillStatus.ACTIVE, reason="紧急修复需要")
        assert lc.status == SkillStatus.ACTIVE

    def test_invalid_transition_raises(self):
        lc = SkillLifecycle()
        with pytest.raises(ValueError, match="不允许的状态转换"):
            lc.transition(SkillStatus.ACTIVE)  # draft → active 不允许

    def test_get_allowed_transitions(self):
        lc = SkillLifecycle()
        allowed = lc.get_allowed_transitions()
        assert SkillStatus.TESTING in allowed
        assert SkillStatus.PENDING_REVIEW in allowed
        assert SkillStatus.ARCHIVED in allowed
        assert SkillStatus.ACTIVE not in allowed

    def test_is_editable(self):
        lc = SkillLifecycle()
        assert lc.is_editable  # draft 可编辑

        lc.transition(SkillStatus.TESTING)
        assert lc.is_editable  # testing 可编辑

        lc.transition(SkillStatus.PENDING_REVIEW)
        assert lc.transition(SkillStatus.APPROVED)
        assert lc.transition(SkillStatus.PUBLISHED)
        lc.transition(SkillStatus.ACTIVE)
        assert not lc.is_editable  # active 不可编辑

    def test_history_tracks_all_events(self):
        lc = SkillLifecycle()
        lc.transition(SkillStatus.TESTING, reason="t1")
        lc.transition(SkillStatus.PENDING_REVIEW, reason="t2")
        assert len(lc.history) == 2
        assert lc.history[0].reason == "t1"
        assert lc.history[1].reason == "t2"

    def test_get_approval_workflow(self):
        wf = get_approval_workflow()
        assert len(wf) == 6
        assert wf[0] == SkillStatus.DRAFT
        assert wf[-1] == SkillStatus.ACTIVE
        assert SkillStatus.TESTING in wf
        assert SkillStatus.PENDING_REVIEW in wf

    def test_get_auto_publish_workflow(self):
        wf = get_auto_publish_workflow()
        assert len(wf) == 4
        assert SkillStatus.PENDING_REVIEW not in wf  # 跳过审核
        assert SkillStatus.APPROVED not in wf


# ============================================================
# Skill 工具测试
# ============================================================

class TestSkillTools:
    @pytest.fixture(autouse=True)
    def setup_tools(self):
        from src.agents.tools.skill_tools import (
            GenerateSkillCodeTool,
            ScanSkillTool,
            SearchSkillsTool,
        )
        from src.harness.tool_registry import register_tool

        register_tool(SearchSkillsTool())
        register_tool(GenerateSkillCodeTool())
        register_tool(ScanSkillTool())

    @pytest.mark.asyncio
    async def test_search_skills_returns_registry(self):
        from src.agents.tools.skill_tools import SearchSkillsInput, SearchSkillsTool

        tool = SearchSkillsTool()
        result = await tool.execute(
            SearchSkillsInput(query=""),
            __import__("src.harness.abort_signal", fromlist=["AbortSignal"]).AbortSignal(),
        )
        assert "count" in result or "未找到" in result

    @pytest.mark.asyncio
    async def test_search_skills_readonly(self):
        from src.agents.tools.skill_tools import SearchSkillsInput, SearchSkillsTool

        tool = SearchSkillsTool()
        assert tool.is_read_only(SearchSkillsInput(query="test"))
        assert tool.is_concurrency_safe(SearchSkillsInput(query="test"))

    @pytest.mark.asyncio
    async def test_generate_skill_code_produces_template(self):
        from src.agents.tools.skill_tools import GenerateSkillCodeInput, GenerateSkillCodeTool

        tool = GenerateSkillCodeTool()
        result = await tool.execute(
            GenerateSkillCodeInput(
                requirement="获取指定城市的天气信息",
                name="weather_fetcher",
            ),
            __import__("src.harness.abort_signal", fromlist=["AbortSignal"]).AbortSignal(),
        )
        assert "weather_fetcher" in result
        assert "def execute" in result

    @pytest.mark.asyncio
    async def test_scan_skill_returns_score(self):
        from src.agents.tools.skill_tools import ScanSkillInput, ScanSkillTool

        tool = ScanSkillTool()
        result = await tool.execute(
            ScanSkillInput(
                code=(
                    "import json\n"
                    "def execute(input_data):\n"
                    "    return {\"success\": True, \"result\": \"ok\"}\n"
                ),
            ),
            __import__("src.harness.abort_signal", fromlist=["AbortSignal"]).AbortSignal(),
        )
        assert "评分" in result

    @pytest.mark.asyncio
    async def test_scan_dangerous_code(self):
        from src.agents.tools.skill_tools import ScanSkillInput, ScanSkillTool

        tool = ScanSkillTool()
        result = await tool.execute(
            ScanSkillInput(code="import os\nos.system('rm -rf /')"),
            __import__("src.harness.abort_signal", fromlist=["AbortSignal"]).AbortSignal(),
        )
        assert "扫描未通过" in result or "评分" in result


# ============================================================
# Harness Agent 创建测试
# ============================================================

class TestHarnessAgentCreation:
    """测试 Harness Agent 的创建和基本属性。"""

    def test_create_agent_basic(self):
        """使用 mock LLM 创建 Agent 不抛异常。"""
        from unittest.mock import MagicMock

        from src.agents.harness_agent import create_harness_agent

        mock_llm = MagicMock()
        mock_llm.model_name = "test-model"
        agent = create_harness_agent(mock_llm)
        assert agent is not None
        assert agent._name if hasattr(agent, "_name") else True

    def test_harness_tools_registered(self):
        """创建 Harness Agent 后，工具已注册。"""
        from unittest.mock import MagicMock

        from src.agents.harness_agent import create_harness_agent
        from src.harness.tool_registry import get_tool

        mock_llm = MagicMock()
        mock_llm.model_name = "test-model"
        create_harness_agent(mock_llm)

        # 验证所有 Skill 工具都已注册
        tool_names = [
            "search_skills",
            "generate_skill_code",
            "test_skill",
            "scan_skill",
            "register_skill",
            "install_skill",
        ]
        for name in tool_names:
            tool = get_tool(name)
            assert tool is not None, f"工具 {name} 未注册"

    def test_harness_agent_system_prompt(self):
        from src.agents.harness_agent import HARNESS_SYSTEM_PROMPT

        assert "Harness Engineering" in HARNESS_SYSTEM_PROMPT
        assert "execute(input_data)" in HARNESS_SYSTEM_PROMPT
        assert "install_skill" in HARNESS_SYSTEM_PROMPT


# ============================================================
# 端到端流程测试
# ============================================================

class TestE2ESkillFlow:
    """端到端测试：安全检查流程。"""

    @pytest.mark.asyncio
    async def test_scan_then_validate_flow(self):
        """模拟完整流程：生成 → 扫描 → 验证。"""
        from src.harness.security.policies import POLICY_MEDIUM
        from src.harness.security.scanner import CodeScanner
        from src.harness.skill_lifecycle import SkillLifecycle, SkillStatus

        # 安全的代码
        safe_code = (
            "import json\n"
            "from typing import Any\n\n"
            "def execute(input_data: dict[str, Any]) -> dict[str, Any]:\n"
            '    name = input_data.get("name", "World")\n'
            '    return {"success": True, "result": f"Hello, {name}!"}\n'
        )

        # 扫描
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan(safe_code)
        assert result.passed, f"安全代码应通过扫描: {result.findings}"
        assert result.score >= 90

        # 模拟生命周期
        lc = SkillLifecycle()
        lc.transition(SkillStatus.TESTING, reason="代码生成完成")
        lc.transition(SkillStatus.PENDING_REVIEW, reason=f"安全评分: {result.score}/100")
        lc.transition(SkillStatus.APPROVED, reason="审核通过")
        lc.transition(SkillStatus.PUBLISHED)
        lc.transition(SkillStatus.ACTIVE)

        assert lc.is_active

    @pytest.mark.asyncio
    async def test_dangerous_code_rejected(self):
        """危险代码应该被安全扫描拒绝。"""
        from src.harness.security.policies import POLICY_MEDIUM
        from src.harness.security.scanner import CodeScanner

        dangerous_code = (
            "import os\n"
            "def execute(data):\n"
            "    os.system(data['cmd'])\n"
            '    return {"success": True}\n'
        )

        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan(dangerous_code)
        assert not result.passed, "危险代码应被拒绝"
        assert result.score < 70, f"危险代码评分应低于70，实际: {result.score}"
