"""
代码安全扫描器。

多层安全扫描：
1. AST 白名单分析 — 模块导入 / 函数调用白名单
2. bandit 静态分析 — Python 安全漏洞检测（可选）
3. 模式匹配 — 危险字符串 / 模式检测
4. 安全评分 — 综合风险评级

使用方式：
    scanner = CodeScanner(policy=get_policy("medium"))
    result = scanner.scan(code)
    if not result.passed:
        for finding in result.findings:
            print(finding)
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from loguru import logger

from src.harness.security.policies import SecurityPolicy


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ScanFinding:
    """单个扫描发现。"""
    severity: Severity
    line: int
    code: str          # 代码片段
    message: str
    rule: str          # 规则名称
    suggestion: str = ""


@dataclass
class ScanResult:
    """扫描结果。"""
    passed: bool
    findings: list[ScanFinding] = field(default_factory=list)
    score: int = 100  # 0-100，100=完全安全
    scan_duration_ms: float = 0.0
    bandit_available: bool = False
    bandit_result: Any = None

    @property
    def errors(self) -> list[ScanFinding]:
        return [f for f in self.findings if f.severity in (Severity.ERROR, Severity.CRITICAL)]

    @property
    def warnings(self) -> list[ScanFinding]:
        return [f for f in self.findings if f.severity == Severity.WARNING]


class CodeScanner:
    """
    代码安全扫描器。

    使用 AST 分析检查代码安全性，可选集成 bandit 进行深度扫描。
    """

    def __init__(self, policy: SecurityPolicy) -> None:
        self._policy = policy
        self._findings: list[ScanFinding] = []

    def scan(self, code: str) -> ScanResult:
        """执行完整安全扫描。"""
        import time

        self._findings = []
        start = time.perf_counter()

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return ScanResult(
                passed=False,
                findings=[ScanFinding(
                    severity=Severity.CRITICAL,
                    line=e.lineno or 0,
                    code=e.text or "",
                    message=f"语法错误: {e.msg}",
                    rule="syntax-check",
                )],
                score=0,
            )

        # 1) AST 导入检查
        self._check_imports(tree)

        # 2) AST 函数调用检查
        self._check_function_calls(tree)

        # 3) 模式匹配检查
        self._check_patterns(code)

        # 4) 复杂度检查
        self._check_complexity(tree, code)

        # 5) Bandit（可选）
        bandit_result = None
        bandit_available = False
        try:
            bandit_result = self._run_bandit(code)
            bandit_available = True
        except Exception as e:
            logger.debug(f"Bandit 扫描跳过: {e}")

        # 计算评分
        score = self._calculate_score()
        passed = not self.errors

        elapsed = (time.perf_counter() - start) * 1000
        return ScanResult(
            passed=passed,
            findings=list(self._findings),
            score=score,
            scan_duration_ms=elapsed,
            bandit_available=bandit_available,
            bandit_result=bandit_result,
        )

    # ── 各阶段检查 ──

    def _check_imports(self, tree: ast.AST) -> None:
        """检查所有导入语句。"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._check_module(alias.name, node.lineno, f"import {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._check_module(node.module, node.lineno, f"from {node.module} import ...")

    def _check_module(self, module_name: str, lineno: int, code: str) -> None:
        """检查模块是否被允许。"""
        root_module = module_name.split(".")[0]

        # 检查禁止列表
        if root_module in self._policy.forbidden_modules:
            self._findings.append(ScanFinding(
                severity=Severity.ERROR,
                line=lineno,
                code=code,
                message=f"禁止导入模块: {root_module}",
                rule="forbidden-module",
                suggestion=f"请使用允许的模块: {', '.join(self._policy.allowed_modules[:8])}...",
            ))
            return

        # 检查白名单
        if self._policy.allowed_modules:
            if root_module not in self._policy.allowed_modules and module_name not in self._policy.allowed_imports:
                self._findings.append(ScanFinding(
                    severity=Severity.WARNING,
                    line=lineno,
                    code=code,
                    message=f"不在白名单中的模块: {module_name}",
                    rule="module-not-whitelisted",
                    suggestion="请将模块添加到 allowed_modules 或 allowed_imports",
                ))

    def _check_function_calls(self, tree: ast.AST) -> None:
        """检查函数调用。"""
        forbidden = set(self._policy.forbidden_functions)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = self._get_call_name(node)
                if func_name in forbidden:
                    self._findings.append(ScanFinding(
                        severity=Severity.CRITICAL,
                        line=node.lineno,
                        code=ast.unparse(node) if hasattr(ast, "unparse") else func_name,
                        message=f"禁止调用危险函数: {func_name}()",
                        rule="forbidden-function",
                        suggestion="请使用安全替代方案或通过工具系统操作",
                    ))

                # 检查 __import__ 属性调用
                if func_name == "__import__":
                    self._findings.append(ScanFinding(
                        severity=Severity.CRITICAL,
                        line=node.lineno,
                        code=func_name,
                        message="禁止调用 __import__()",
                        rule="forbidden-function",
                    ))

    def _check_patterns(self, code: str) -> None:
        """模式匹配检查 — 检测危险代码模式。"""
        patterns: list[tuple[str, Severity, str, str, str]] = [
            # (regex, severity, rule, message, suggestion)
            (r"os\.system\s*\(", Severity.CRITICAL, "os-system",
             "检测到 os.system() 调用", "请使用沙箱的 execute_command"),
            (r"subprocess\.\w+\s*\(", Severity.CRITICAL, "subprocess",
             "检测到 subprocess 调用", "请使用沙箱的 execute_command"),
            (r"eval\s*\(", Severity.CRITICAL, "eval",
             "检测到 eval() 调用", "请勿动态执行代码"),
            (r"exec\s*\(", Severity.CRITICAL, "exec",
             "检测到 exec() 调用", "请勿动态执行代码"),
            (r"__import__\s*\(", Severity.CRITICAL, "import-invoke",
             "检测到 __import__() 调用", "请使用标准 import 语句"),
            (r"(rm\s+-rf|mkfs\.|dd\s+if=)", Severity.CRITICAL, "dangerous-shell",
             "检测到危险 Shell 命令模式", "此命令可能造成不可逆损害"),
            (r"while\s+True\s*:", Severity.WARNING, "infinite-loop",
             "检测到无限循环 while True", "请添加明确的退出条件或超时保护"),
        ]

        for line_no, line_text in enumerate(code.split("\n"), 1):
            for pattern, severity, rule, msg, suggestion in patterns:
                if re.search(pattern, line_text, re.IGNORECASE):
                    self._findings.append(ScanFinding(
                        severity=severity,
                        line=line_no,
                        code=line_text.strip()[:120],
                        message=msg,
                        rule=rule,
                        suggestion=suggestion,
                    ))

    def _check_complexity(self, tree: ast.AST, code: str) -> None:
        """检查代码复杂度。"""
        lines = code.split("\n")

        # 代码行数限制
        if len(lines) > 500:
            self._findings.append(ScanFinding(
                severity=Severity.WARNING,
                line=0,
                code=f"代码共 {len(lines)} 行",
                message=f"代码过长 ({len(lines)} 行)，建议不超过 500 行",
                rule="code-too-long",
                suggestion="请精简代码或拆分为多个 Skill",
            ))

        # AST 节点数限制
        node_count = sum(1 for _ in ast.walk(tree))
        if node_count > 2000:
            self._findings.append(ScanFinding(
                severity=Severity.WARNING,
                line=0,
                code=f"AST 节点 {node_count} 个",
                message="代码结构过于复杂",
                rule="code-too-complex",
                suggestion="请简化代码逻辑",
            ))

    def _run_bandit(self, code: str) -> Any | None:
        """运行 bandit 静态安全分析。"""
        try:
            import bandit.core.config as bandit_config
            import bandit.core.manager as bandit_manager

            # Bandit 配置
            b_conf = bandit_config.BanditConfig()
            b_mgr = bandit_manager.BanditManager(b_conf, "file", agg_type="file")

            # 写入临时文件给 bandit 扫描
            import tempfile
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
                f.write(code)
                tmp = f.name

            try:
                b_mgr.discover_files([tmp], recursive=False)
                b_mgr.run_tests()
                return {
                    "results": [
                        {
                            "severity": r.severity,
                            "confidence": r.confidence,
                            "text": r.text,
                            "line": r.lineno,
                            "test": r.test_id,
                        }
                        for r in b_mgr.results
                    ],
                    "metrics": b_mgr.metrics.data if hasattr(b_mgr, "metrics") else {},
                }
            finally:
                import os
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        except ImportError:
            return None
        except Exception as e:
            logger.debug(f"Bandit 扫描异常: {e}")
            return None

    def _calculate_score(self) -> int:
        """计算安全评分 0-100。"""
        score = 100
        for f in self._findings:
            if f.severity == Severity.CRITICAL:
                score -= 30
            elif f.severity == Severity.ERROR:
                score -= 15
            elif f.severity == Severity.WARNING:
                score -= 5
            elif f.severity == Severity.INFO:
                score -= 1
        return max(0, min(100, score))

    @property
    def errors(self) -> list[ScanFinding]:
        return [f for f in self._findings if f.severity in (Severity.ERROR, Severity.CRITICAL)]

    @staticmethod
    def _get_call_name(node: ast.Call) -> str:
        """获取函数调用名。"""
        if isinstance(node.func, ast.Name):
            return node.func.id
        if isinstance(node.func, ast.Attribute):
            return node.func.attr
        return ""
