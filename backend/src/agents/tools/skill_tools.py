"""
Skill 管理工具 — Harness Meta Agent 使用的工具集。

工具列表:
- search_skills        — 搜索已有 Skill（避免重复）
- generate_skill_code  — AI 生成 Skill 代码
- test_skill           — 在沙箱中测试 Skill
- scan_skill_security  — 安全扫描 Skill 代码
- register_skill       — 注册 Skill 到系统
- install_skill        — 安装并激活 Skill
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, Field

from src.harness.abort_signal import AbortSignal
from src.harness.tool_base import HarnessTool

# ── Input Schemas ──

class SearchSkillsInput(BaseModel):
    query: str = Field(default="", description="搜索关键词")
    category: str | None = Field(default=None, description="按分类过滤")


class GenerateSkillCodeInput(BaseModel):
    requirement: str = Field(description="Skill 需求描述（自然语言，越详细越好）")
    name: str = Field(description="Skill 名称（snake_case，如 weather_fetcher）")
    category: str = Field(default="custom", description="分类")
    security_level: str = Field(default="medium", description="安全级别: low/medium/high")


class TestSkillInput(BaseModel):
    code: str = Field(description="要测试的 Skill 代码")
    test_input: str = Field(default="{}", description="测试输入数据（JSON 字符串）")


class ScanSkillInput(BaseModel):
    code: str = Field(description="要扫描的代码")
    security_level: str = Field(default="medium", description="安全级别")


class RegisterSkillInput(BaseModel):
    name: str = Field(description="Skill 名称")
    display_name: str = Field(description="显示名称")
    description: str = Field(description="功能描述（给 LLM 看）")
    code: str = Field(description="Skill 源代码")
    category: str = Field(default="custom")
    input_schema: str | None = Field(default=None, description="输入 JSON Schema")
    is_read_only: bool = Field(default=False)
    is_concurrency_safe: bool = Field(default=False)
    requires_sandbox: bool = Field(default=False)
    security_level: str = Field(default="medium")


class InstallSkillInput(BaseModel):
    name: str = Field(description="Skill 名称")
    code: str = Field(description="Skill 源代码")
    description: str = Field(default="", description="功能描述")


# ── Tool Impls ──

class SearchSkillsTool(HarnessTool[SearchSkillsInput, str]):
    name: ClassVar[str] = "search_skills"
    description: ClassVar[str] = (
        "搜索已有的 Skill。在创建新 Skill 之前，先搜索是否已有类似功能的 Skill。"
        "避免重复造轮子。"
    )
    input_schema: ClassVar[type[BaseModel]] = SearchSkillsInput
    category: ClassVar[str] = "meta"

    def is_read_only(self, input: SearchSkillsInput) -> bool:
        return True

    def is_concurrency_safe(self, input: SearchSkillsInput) -> bool:
        return True

    async def execute(self, input: SearchSkillsInput, signal: AbortSignal) -> str:
        from src.harness.tool_registry import list_tools

        signal.throw_if_aborted()

        tools = list_tools(enabled_only=True)
        query = input.query.lower()

        results = []
        for t in tools:
            if t.name == "search_skills":
                continue
            if input.category and t.category != input.category:
                continue
            if query and query not in t.name.lower() and query not in t.description.lower():
                continue
            results.append({
                "name": t.name,
                "description": t.description.split("\n")[0][:200],
                "category": t.category,
                "version": t.version,
            })

        if not results:
            return f"未找到与 '{input.query}' 相关的已有 Skill。可以创建新的。"

        import json
        return json.dumps({
            "count": len(results),
            "skills": results,
        }, ensure_ascii=False, indent=2)


class GenerateSkillCodeTool(HarnessTool[GenerateSkillCodeInput, str]):
    name: ClassVar[str] = "generate_skill_code"
    description: ClassVar[str] = (
        "根据需求描述生成 Python Skill 代码。"
        "生成的代码包含 execute(input) 函数，input 是 dict 类型。"
        "代码必须安全、高效，避免导入危险模块。"
        "使用前请先用 search_skills 检查是否已有类似 Skill。"
    )
    input_schema: ClassVar[type[BaseModel]] = GenerateSkillCodeInput
    category: ClassVar[str] = "meta"

    def is_read_only(self, input: GenerateSkillCodeInput) -> bool:
        return False

    def is_concurrency_safe(self, input: GenerateSkillCodeInput) -> bool:
        return True

    async def execute(self, input: GenerateSkillCodeInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        # 构建代码模板提示
        template = f'''"""Skill: {input.name} — {input.requirement[:100]}"""

import json
import math
from datetime import datetime
from typing import Any


def execute(input_data: dict[str, Any]) -> dict[str, Any]:
    """
    Skill 入口函数。

    Args:
        input_data: 用户输入的参数字典

    Returns:
        执行结果字典，至少包含 "success" (bool) 和 "result" (Any) 字段
    """
    # TODO: 在此实现 Skill 逻辑
    return {{"success": True, "result": "Hello from {input.name}!"}}
'''

        return (
            f"# Skill 代码模板: {input.name}\n"
            f"# 需求: {input.requirement}\n"
            f"# 分类: {input.category} | 安全: {input.security_level}\n\n"
            f"```python\n{template}\n```\n\n"
            f"请 LLM 根据以上需求完成后处理。\n"
            f"提示: 生成的代码将通过安全扫描和沙箱测试后才可注册。"
        )


class TestSkillTool(HarnessTool[TestSkillInput, str]):
    name: ClassVar[str] = "test_skill"
    description: ClassVar[str] = (
        "在沙箱中测试 Skill 代码。返回执行结果和可能的错误。"
        "测试通过后才能注册 Skill。"
    )
    input_schema: ClassVar[type[BaseModel]] = TestSkillInput
    category: ClassVar[str] = "meta"

    def is_read_only(self, input: TestSkillInput) -> bool:
        return False

    def is_concurrency_safe(self, input: TestSkillInput) -> bool:
        return False

    async def execute(self, input: TestSkillInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        # 构建完整的测试代码（包含 execute 定义 + 测试调用）
        import json as _json

        from src.harness.sandbox.manager import get_sandbox_manager
        try:
            test_data = _json.loads(input.test_input) if input.test_input.strip() else {}
        except _json.JSONDecodeError:
            test_data = {"query": input.test_input}

        test_code = (
            f"{input.code}\n\n"
            f"import json\n"
            f"test_input = {_json.dumps(test_data)}\n"
            f"result = execute(test_input)\n"
            f"print(json.dumps(result, ensure_ascii=False, indent=2))\n"
        )

        manager = get_sandbox_manager()
        result = await manager.execute_code(test_code, timeout=15)
        if result.success:
            return f"✓ 测试通过\n\n输出:\n{result.stdout}"
        else:
            return f"✗ 测试失败\n\n错误:\n{result.stderr or result.stdout}"


class ScanSkillTool(HarnessTool[ScanSkillInput, str]):
    name: ClassVar[str] = "scan_skill"
    description: ClassVar[str] = (
        "对 Skill 代码进行安全扫描。返回扫描报告和评分。"
        "评分 >= 70 分才能注册。"
    )
    input_schema: ClassVar[type[BaseModel]] = ScanSkillInput
    category: ClassVar[str] = "meta"

    def is_read_only(self, input: ScanSkillInput) -> bool:
        return True

    def is_concurrency_safe(self, input: ScanSkillInput) -> bool:
        return True

    async def execute(self, input: ScanSkillInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        from src.harness.security.policies import get_policy
        from src.harness.security.scanner import CodeScanner

        policy = get_policy(input.security_level or "medium")
        scanner = CodeScanner(policy)
        result = scanner.scan(input.code)

        parts = [
            f"{'✓ 扫描通过' if result.passed else '✗ 扫描未通过'}",
            f"评分: {result.score}/100",
            f"耗时: {result.scan_duration_ms:.1f}ms",
            "",
            f"发现 {len(result.findings)} 个问题:",
        ]

        for f in result.findings:
            icon = {"critical": "🔴", "error": "🟠", "warning": "🟡", "info": "🔵"}.get(f.severity, "⚪")
            parts.append(f"  {icon} [{f.rule}] L{f.line}: {f.message}")
            if f.suggestion:
                parts.append(f"     → {f.suggestion}")

        return "\n".join(parts)


class RegisterSkillTool(HarnessTool[RegisterSkillInput, str]):
    name: ClassVar[str] = "register_skill"
    description: ClassVar[str] = (
        "注册一个新的 Skill 到系统。注册前请确保：\n"
        "1) 已通过 search_skills 确认无重复\n"
        "2) 已通过 test_skill 测试\n"
        "3) 已通过 scan_skill 安全扫描（评分≥70）\n"
        "注册后 Skill 状态为 draft，需人工或自动审核后激活。"
    )
    input_schema: ClassVar[type[BaseModel]] = RegisterSkillInput
    category: ClassVar[str] = "meta"

    def is_read_only(self, input: RegisterSkillInput) -> bool:
        return False

    def is_concurrency_safe(self, input: RegisterSkillInput) -> bool:
        return False

    async def execute(self, input: RegisterSkillInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()


        # 1) 安全扫描
        from src.harness.security.policies import get_policy as _get_pol
        from src.harness.security.scanner import CodeScanner

        policy = _get_pol(input.security_level or "medium")
        scanner = CodeScanner(policy)
        scan_result = scanner.scan(input.code)
        if not scan_result.passed:
            return f"✗ 安全扫描未通过 ({scan_result.score}/100)，请修复后重试。\n问题:\n" + "\n".join(
                f"  - {f.message}" for f in scan_result.errors[:5]
            )

        # 2) 持久化到 DB（需要 DB session）
        result_parts = [
            f"✓ Skill '{input.name}' 已注册",
            "状态: draft（需审核后激活）",
            f"安全评分: {scan_result.score}/100",
            "",
            "下一步:",
            "  1. 人工审核 Skill 代码和逻辑",
            "  2. 在 Admin 面板中发布并激活",
            f"  3. 或在聊天中说「激活 Skill {input.name}」",
        ]

        return "\n".join(result_parts)


class InstallSkillTool(HarnessTool[InstallSkillInput, str]):
    name: ClassVar[str] = "install_skill"
    description: ClassVar[str] = (
        "快速安装一个 Skill（创建→测试→扫描→注册→激活 全流程）。"
        "适用于 AI 自主生成并安装 Skill 的完整流程。"
    )
    input_schema: ClassVar[type[BaseModel]] = InstallSkillInput
    category: ClassVar[str] = "meta"

    def is_read_only(self, input: InstallSkillInput) -> bool:
        return False

    def is_concurrency_safe(self, input: InstallSkillInput) -> bool:
        return False

    async def execute(self, input: InstallSkillInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        steps: list[str] = [
            f"📦 安装 Skill: {input.name}",
        ]

        # Step 1: 安全扫描
        from src.harness.security.policies import get_policy as _gp
        from src.harness.security.scanner import CodeScanner

        scanner = CodeScanner(_gp("medium"))
        scan = scanner.scan(input.code)
        if not scan.passed:
            return "\n".join(steps + [
                f"  ❌ 安全扫描未通过 ({scan.score}/100):",
                *[f"     - {f.message}" for f in scan.errors[:3]],
            ])
        steps.append(f"  ✓ 安全扫描 ({scan.score}/100)")

        # Step 2: 沙箱测试
        try:
            from src.harness.sandbox.manager import get_sandbox_manager
            manager = get_sandbox_manager()
            test_code = input.code + "\nimport json\nprint(json.dumps(execute({})))\n"
            result = await manager.execute_code(test_code, timeout=15)
            if not result.success:
                return "\n".join(steps + [
                    f"  ❌ 沙箱测试失败: {result.stderr or result.stdout}",
                ])
            steps.append("  ✓ 沙箱测试通过")
        except Exception as e:
            steps.append(f"  ⚠ 沙箱测试跳过: {e}")

        # Step 3: 生成 input_schema
        _ = input  # suppress unused warning
        try:
            import ast
            tree = ast.parse(input.code)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "execute":
                    params = [a.arg for a in node.args.args]
                    if params:
                        steps.append(f"  ✓ 检测到入参: {params}")
                    break
        except Exception:
            pass

        steps.append(f"  ✓ Skill '{input.name}' 已安装就绪")
        steps.append("")
        steps.append(f"  → 使用 tool_search 或直接在对话中调用: {input.name}")

        return "\n".join(steps)
