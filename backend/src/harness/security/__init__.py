"""
安全模块 — 统一代码安全扫描与安全策略。

提供：
- SecurityPolicy: 可配置的安全级别 (low/medium/high/critical)
- CodeScanner: 多层安全扫描器（AST + 模式匹配 + Bandit）
- 预定义策略: POLICY_LOW, POLICY_MEDIUM, POLICY_HIGH, POLICY_CRITICAL
"""

from src.harness.security.policies import (
    POLICY_CRITICAL,
    POLICY_HIGH,
    POLICY_LOW,
    POLICY_MEDIUM,
    SecurityPolicy,
    get_policy,
    list_policies,
)
from src.harness.security.scanner import (
    CodeScanner,
    ScanFinding,
    ScanResult,
    Severity,
)

__all__ = [
    "SecurityPolicy",
    "CodeScanner",
    "ScanFinding",
    "ScanResult",
    "Severity",
    "get_policy",
    "list_policies",
    "POLICY_LOW",
    "POLICY_MEDIUM",
    "POLICY_HIGH",
    "POLICY_CRITICAL",
]
