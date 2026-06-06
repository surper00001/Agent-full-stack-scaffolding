"""
安全策略配置。

定义 Skill 代码的安全级别和对应的限制策略。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SecurityPolicy:
    """安全策略 — 定义 Skill 可以做什么、不能做什么。"""

    # 安全级别标识
    level: str  # low / medium / high / critical

    # 允许的 Python 模块
    allowed_modules: list[str] = field(default_factory=list)

    # 允许的导入（精确匹配）
    allowed_imports: list[str] = field(default_factory=list)

    # 禁止的模块 / 函数
    forbidden_modules: list[str] = field(default_factory=list)
    forbidden_functions: list[str] = field(default_factory=list)

    # 运行时限制
    max_execution_time_seconds: int = 60
    max_output_size_bytes: int = 50_000
    max_memory_mb: int = 256

    # 网络
    network_allowed: bool = False
    network_whitelist: list[str] = field(default_factory=list)

    # 文件系统
    filesystem_allowed: bool = False
    filesystem_read_only: bool = True
    filesystem_paths: list[str] = field(default_factory=list)  # 允许访问的路径

    # 是否需要人工审核
    requires_approval: bool = False


# ── 预定义安全级别 ──

POLICY_LOW = SecurityPolicy(
    level="low",
    # 宽松：基本 Python + 常见库
    allowed_modules=[
        "json", "math", "datetime", "collections", "itertools",
        "functools", "re", "string", "textwrap", "random",
        "typing", "dataclasses", "enum", "pathlib",
    ],
    forbidden_modules=[
        "os", "subprocess", "shutil", "socket", "ctypes",
        "importlib", "sys", "http.server",
    ],
    forbidden_functions=["eval", "exec", "compile", "open", "__import__"],
    max_execution_time_seconds=30,
    max_output_size_bytes=20_000,
    max_memory_mb=128,
    network_allowed=False,
    filesystem_allowed=False,
    requires_approval=False,
)

POLICY_MEDIUM = SecurityPolicy(
    level="medium",
    # 中等：允许 HTTP 请求、文件读取
    allowed_modules=[
        "json", "math", "datetime", "collections", "itertools",
        "functools", "re", "string", "textwrap", "random",
        "typing", "dataclasses", "enum", "pathlib",
        "requests", "httpx", "urllib.parse", "csv", "hashlib",
        "base64", "binascii", "uuid", "xml.etree.ElementTree",
    ],
    forbidden_modules=[
        "os", "subprocess", "shutil", "socket", "ctypes",
        "importlib", "sys",
    ],
    forbidden_functions=["eval", "exec", "compile", "__import__"],
    max_execution_time_seconds=60,
    max_output_size_bytes=100_000,
    max_memory_mb=256,
    network_allowed=True,
    network_whitelist=["api.github.com", "pypi.org", "files.pythonhosted.org"],
    filesystem_allowed=True,
    filesystem_read_only=True,
    filesystem_paths=["/workspace"],
    requires_approval=False,
)

POLICY_HIGH = SecurityPolicy(
    level="high",
    # 高安全：需要审核，严格限制
    allowed_modules=[
        "json", "math", "datetime", "collections", "itertools",
        "functools", "re", "string",
        "typing", "dataclasses", "enum",
    ],
    forbidden_modules=[
        "os", "subprocess", "shutil", "socket", "ctypes",
        "importlib", "sys", "requests", "httpx",
        "http", "urllib", "pickle",
    ],
    forbidden_functions=["eval", "exec", "compile", "open", "__import__"],
    max_execution_time_seconds=15,
    max_output_size_bytes=10_000,
    max_memory_mb=64,
    network_allowed=False,
    filesystem_allowed=False,
    requires_approval=True,
)

POLICY_CRITICAL = SecurityPolicy(
    level="critical",
    # 最高安全：必须审核，沙箱隔离
    allowed_modules=[
        "json", "math", "datetime",
        "typing", "dataclasses",
    ],
    forbidden_modules=[
        "os", "subprocess", "shutil", "socket", "ctypes",
        "importlib", "sys", "requests", "httpx",
        "http", "urllib", "pickle", "pathlib", "csv",
        "hashlib", "base64", "random",
    ],
    forbidden_functions=["eval", "exec", "compile", "open", "__import__"],
    max_execution_time_seconds=10,
    max_output_size_bytes=5_000,
    max_memory_mb=32,
    network_allowed=False,
    filesystem_allowed=False,
    requires_approval=True,
)


# ── 策略注册表 ──

_POLICIES: dict[str, SecurityPolicy] = {
    "low": POLICY_LOW,
    "medium": POLICY_MEDIUM,
    "high": POLICY_HIGH,
    "critical": POLICY_CRITICAL,
}


def get_policy(level: str) -> SecurityPolicy:
    """获取指定安全级别的策略。"""
    return _POLICIES.get(level, POLICY_MEDIUM)


def list_policies() -> dict[str, SecurityPolicy]:
    """列出所有安全策略。"""
    return dict(_POLICIES)
