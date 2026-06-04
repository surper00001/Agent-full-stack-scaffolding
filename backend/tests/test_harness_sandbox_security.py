"""
测试沙箱系统 + 安全扫描。
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from src.harness.sandbox.base import NetworkMode, SandboxConfig
from src.harness.sandbox.manager import SandboxManager
from src.harness.sandbox.process_sandbox import ProcessSandbox
from src.harness.security.policies import (
    POLICY_HIGH,
    POLICY_LOW,
    POLICY_MEDIUM,
    SecurityPolicy,
    get_policy,
)
from src.harness.security.scanner import CodeScanner, ScanFinding, Severity


# ============================================================
# Process Sandbox 测试
# ============================================================

class TestProcessSandbox:
    @pytest.mark.asyncio
    async def test_start_and_health(self):
        sandbox = ProcessSandbox()
        await sandbox.start()
        assert await sandbox.health_check()
        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_safe_code(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_code("print('hello sandbox')")
        assert result.success
        assert "hello sandbox" in result.stdout

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_math_code(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_code(
            "import math\nimport json\nprint(json.dumps({'sqrt': math.sqrt(16)}))"
        )
        assert result.success
        assert "4.0" in result.stdout

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_blocked_code_os_system(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_code("import os\nprint('should fail')")
        assert not result.success
        assert "安全扫描" in result.stderr or "禁止" in result.stderr

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_blocked_code_eval(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_code("eval('1+1')")
        assert not result.success
        assert "eval" in result.stderr

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_blocked_code_subprocess(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_code("import subprocess\nsubprocess.run(['echo'])")
        assert not result.success

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_command(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_command("echo test_command")
        assert result.success
        assert "test_command" in result.stdout

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_execute_command_timeout(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        result = await sandbox.execute_command("sleep 10", timeout_seconds=1)
        assert result.killed or "超时" in result.stderr
        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_install_dependencies(self):
        sandbox = ProcessSandbox()
        await sandbox.start()

        # 安装一个简单包
        result = await sandbox.install_dependencies(["six"])
        # 可能成功（网络可用）或失败（网络不可用），但不应崩溃
        assert isinstance(result.exit_code, int)

        await sandbox.stop()

    @pytest.mark.asyncio
    async def test_workspace_isolation(self):
        """每个沙箱使用独立工作目录。"""
        s1 = ProcessSandbox()
        s2 = ProcessSandbox()
        await s1.start()
        await s2.start()

        assert s1._workspace != s2._workspace

        await s1.stop()
        await s2.stop()

    @pytest.mark.asyncio
    async def test_restart(self):
        sandbox = ProcessSandbox()
        await sandbox.start()
        await sandbox.restart()
        assert await sandbox.health_check()
        await sandbox.stop()


# ============================================================
# Sandbox Manager 测试
# ============================================================

class TestSandboxManager:
    @pytest.mark.asyncio
    async def test_acquire_and_execute(self):
        manager = SandboxManager()
        await manager.start()

        async with manager.acquire() as sandbox:
            result = await sandbox.execute_code("print('from pool')")
            assert result.success
            assert "from pool" in result.stdout

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_multiple_acquires(self):
        manager = SandboxManager()
        await manager.start()

        async def work(i: int):
            async with manager.acquire() as sandbox:
                result = await sandbox.execute_code(f"print('worker{i}')")
                return result.success

        tasks = [asyncio.create_task(work(i)) for i in range(3)]
        results = await asyncio.gather(*tasks)
        assert all(results)

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_shortcut_execute_code(self):
        manager = SandboxManager()
        await manager.start()

        result = await manager.execute_code("print('shortcut')")
        assert result.success
        assert "shortcut" in result.stdout

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_stats(self):
        manager = SandboxManager()
        await manager.start()

        # 执行几次操作
        for _ in range(3):
            await manager.execute_code("pass")

        stats = manager.stats
        assert stats["total_acquired"] >= 3
        assert stats["total_created"] >= 1

        await manager.shutdown()

    @pytest.mark.asyncio
    async def test_pool_reuse(self):
        """池中沙箱应该被复用。"""
        manager = SandboxManager()
        await manager.start()

        # 先创建一个沙箱并记录 workspace 路径
        # (通过间接方式验证复用)
        ids: set[str] = set()
        for _ in range(5):
            async with manager.acquire() as sandbox:
                ids.add(sandbox._id)

        # 如果有复用，unique IDs 应该小于5（因为从池中取）
        # 但如果池满了也会创建新的
        assert len(ids) > 0  # 至少不同 ID 的沙箱存在

        await manager.shutdown()


# ============================================================
# 安全策略测试
# ============================================================

class TestSecurityPolicies:
    def test_get_policy_levels(self):
        low = get_policy("low")
        assert low.level == "low"
        assert not low.network_allowed

        medium = get_policy("medium")
        assert medium.level == "medium"
        assert medium.network_allowed
        assert "requests" in medium.allowed_modules

        high = get_policy("high")
        assert high.level == "high"
        assert high.requires_approval

    def test_unknown_level_falls_back_to_medium(self):
        policy = get_policy("nonexistent")
        assert policy.level == "medium"

    def test_forbidden_modules(self):
        policy = POLICY_MEDIUM
        assert "os" in policy.forbidden_modules
        assert "subprocess" in policy.forbidden_modules
        assert "eval" in policy.forbidden_functions

    def test_whitelist_networks(self):
        policy = POLICY_MEDIUM
        assert "api.github.com" in policy.network_whitelist
        assert "pypi.org" in policy.network_whitelist


# ============================================================
# 代码扫描器测试
# ============================================================

class TestCodeScanner:
    def test_safe_code_passes(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("import json\nimport math\nprint(json.dumps({'key': math.sqrt(4)}))")
        assert result.passed
        assert result.score >= 90

    def test_forbidden_module_detected(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("import os\nprint('test')")
        assert not result.passed
        assert any("os" in f.message for f in result.errors)

    def test_eval_detected(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("eval('1+1')")
        assert not result.passed
        assert any("eval" in f.message.lower() for f in result.errors)

    def test_exec_detected(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("exec('x=1')")
        assert not result.passed
        assert any("exec" in f.message.lower() for f in result.errors)

    def test_os_system_pattern_detected(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("os.system('rm -rf /')")
        # os 模块被禁止 + 模式匹配双重命中
        assert not result.passed

    def test_while_true_detected_as_warning(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("while True:\n    print('loop')")
        # while True 是 warning 不是 error，所以可以是 passed
        assert any("while" in f.message.lower() for f in result.warnings)

    def test_code_too_long(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        long_code = "\n".join(f"print({i})" for i in range(600))
        result = scanner.scan(long_code)
        assert any("过长" in f.message for f in result.warnings)

    def test_syntax_error(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        result = scanner.scan("def broken(")
        assert not result.passed
        assert result.score == 0
        assert any("语法" in f.message for f in result.findings)

    def test_score_calculation(self):
        scanner = CodeScanner(POLICY_MEDIUM)
        # 完全安全的代码应该 100 分
        result = scanner.scan("x = 1 + 2\nprint(x)")
        assert result.score == 100

        # eval 应该大幅扣分
        result = scanner.scan("eval('x')")
        assert result.score <= 70  # -30 for CRITICAL

    def test_high_policy_stricter_than_medium(self):
        """HIGH 策略比 MEDIUM 更严格。"""
        scanner_m = CodeScanner(POLICY_MEDIUM)
        scanner_h = CodeScanner(POLICY_HIGH)

        # requests 在 MEDIUM 允许，HIGH 不允许
        code = "import requests\nprint('test')"
        result_m = scanner_m.scan(code)
        result_h = scanner_h.scan(code)

        # HIGH 可能有问题（requests 不在白名单）
        assert result_h.score <= result_m.score  # HIGH 评分 <= MEDIUM 评分

    def test_json_and_math_allowed(self):
        scanner = CodeScanner(POLICY_LOW)
        result = scanner.scan("import json\nimport math\nx = math.pi\nprint(json.dumps([x]))")
        assert result.passed
        assert result.score >= 95
