"""
Sandbox 抽象接口。

定义沙箱执行的标准契约，支持多种后端实现：
- Docker 容器（WSL2）
- 子进程（开发用）
- 未来可扩展：gVisor、Firecracker、Kubernetes Pod
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SandboxStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    FAILED = "failed"
    TERMINATED = "terminated"


class NetworkMode(str, Enum):
    """沙箱网络模式。"""
    NONE = "none"         # 完全无网络
    INTERNAL = "internal" # 仅容器间通信
    WHITELIST = "whitelist" # 白名单域名可访问
    FULL = "full"         # 完全网络访问（仅限信任 Skill）


@dataclass
class SandboxConfig:
    """沙箱配置。"""
    image: str = "python:3.12-slim"
    cpu_limit: float = 0.5          # CPU 核心数
    memory_mb: int = 256            # 内存限制（MB）
    disk_mb: int = 512              # 磁盘限制（MB）
    timeout_seconds: int = 60       # 默认超时
    network: NetworkMode = NetworkMode.NONE
    workspace_mount: str = ""       # 宿主机目录→沙箱内挂载
    environment: dict[str, str] = field(default_factory=dict)
    read_only_rootfs: bool = True   # 根文件系统只读


@dataclass
class SandboxResult:
    """沙箱执行结果。"""
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: float
    truncated: bool = False         # 输出是否被截断
    killed: bool = False            # 是否被强制终止（超时/OOM）
    sandbox_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and not self.killed

    @property
    def output(self) -> str:
        """合并的标准输出和错误输出。"""
        parts = []
        if self.stdout.strip():
            parts.append(self.stdout.rstrip())
        if self.stderr.strip():
            parts.append(f"[stderr]\n{self.stderr.rstrip()}")
        return "\n".join(parts)


class BaseSandbox(ABC):
    """
    沙箱抽象基类。

    每个 Sandbox 实例代表一个独立的执行环境。
    支持代码执行、命令执行、依赖安装。
    """

    def __init__(self, config: SandboxConfig) -> None:
        self.config = config
        self._status = SandboxStatus.IDLE
        self._created_at = time.time()
        self._execution_count = 0

    @property
    def status(self) -> SandboxStatus:
        return self._status

    @property
    def age_seconds(self) -> float:
        return time.time() - self._created_at

    @property
    def execution_count(self) -> int:
        return self._execution_count

    @abstractmethod
    async def start(self) -> None:
        """启动沙箱环境。"""
        ...

    @abstractmethod
    async def execute_code(
        self,
        code: str,
        timeout_seconds: int | None = None,
        security_policy: Any | None = None,
    ) -> SandboxResult:
        """在沙箱中执行 Python 代码。

        Args:
            code: Python 源代码
            timeout_seconds: 执行超时（秒），None 使用默认配置
            security_policy: SecurityPolicy 实例，None 使用默认 medium 策略
        """
        ...

    @abstractmethod
    async def execute_command(
        self,
        command: str,
        timeout_seconds: int | None = None,
        working_dir: str = "/workspace",
    ) -> SandboxResult:
        """在沙箱中执行 Shell 命令。"""
        ...

    @abstractmethod
    async def install_dependencies(self, packages: list[str]) -> SandboxResult:
        """在沙箱中安装 pip 依赖。"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """检查沙箱是否健康可用。"""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """清理沙箱资源。"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止沙箱。"""
        ...

    @abstractmethod
    async def restart(self) -> None:
        """重启沙箱。"""
        ...
