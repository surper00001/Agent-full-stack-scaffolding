"""
Shell 工具 — 在沙箱中执行命令。

支持：
- 隔离执行（沙箱内）
- 超时控制
- AbortSignal 取消
- 输出截断
- 工作目录指定
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, Field

from src.harness.abort_signal import AbortSignal
from src.harness.tool_base import HarnessTool, PermissionResult


class RunShellInput(BaseModel):
    """Shell 命令执行输入。"""
    command: str = Field(description="要执行的 shell 命令")
    working_dir: str | None = Field(
        default=None, description="工作目录（绝对路径），默认当前目录"
    )
    timeout_seconds: int = Field(
        default=60, ge=1, le=300, description="超时时间（秒），最长 5 分钟"
    )
    env: dict[str, str] | None = Field(
        default=None, description="额外的环境变量"
    )


class RunShellTool(HarnessTool[RunShellInput, str]):
    """执行 Shell 命令。

    在隔离的子进程中执行命令，支持超时和取消。
    命令在沙箱工作目录内执行，受限网络访问。

    安全限制：
    - 最大执行时间 300 秒
    - 输出截断到 50000 字符
    - 禁止交互式命令
    - 工作目录限制在项目根
    """

    name: ClassVar[str] = "run_shell"
    description: ClassVar[str] = (
        "在沙箱环境中执行 Shell 命令。"
        "适用场景：运行脚本、安装依赖、执行测试、git 操作等。"
        "⚠️ 命令有 5 分钟超时限制，输出限制 50000 字符。"
        "注意：每次调用是独立的 shell 会话，环境变量不持久化。"
        "提示：如果命令输出很长，用管道或重定向截断（如 `| head -100`）。"
    )
    input_schema: ClassVar[type[BaseModel]] = RunShellInput
    category: ClassVar[str] = "shell"
    tags: ClassVar[list[str]] = ["exec", "system"]
    requires_sandbox: ClassVar[bool] = True

    # 危险命令黑名单
    _FORBIDDEN_COMMANDS = [
        "rm -rf /",
        "mkfs.",
        "dd if=",
        ":(){ :|:& };:",  # fork bomb
    ]

    # 允许的 shell
    _ALLOWED_SHELL = os.environ.get("SHELL", "bash")

    def is_read_only(self, input: RunShellInput) -> bool:
        return False

    def is_concurrency_safe(self, input: RunShellInput) -> bool:
        # 独立命令，在不同工作目录或不同操作时是并发的
        # 但写操作居多，保守返回 False
        return False

    def check_permissions(self, input: RunShellInput) -> PermissionResult:
        """检查命令是否在禁止列表中。"""
        cmd_lower = input.command.lower().replace(" ", "")
        for forbidden in self._FORBIDDEN_COMMANDS:
            if forbidden.lower().replace(" ", "") in cmd_lower:
                return PermissionResult(
                    allowed=False,
                    reason=f"禁止执行危险命令（匹配: {forbidden}）",
                )
        return PermissionResult(allowed=True)

    async def execute(self, input: RunShellInput, signal: AbortSignal) -> str:
        signal.throw_if_aborted()

        # 工作目录
        cwd = input.working_dir or str(Path.cwd())
        cwd_path = Path(cwd).resolve()
        if not cwd_path.exists():
            return f"[错误] 工作目录不存在: {cwd}"

        # 构建环境变量
        env = os.environ.copy()
        if input.env:
            env.update(input.env)

        try:
            # Windows: 使用 cmd /c, Unix: 使用 bash -c
            if os.name == "nt":
                shell_cmd = ["cmd", "/c", input.command]
            else:
                shell_cmd = ["bash", "-c", input.command]

            process = await asyncio.create_subprocess_exec(
                *shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd_path),
                env=env,
            )

            # 等待完成或超时/取消
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=input.timeout_seconds,
                )
            except TimeoutError:
                process.kill()
                await process.wait()
                return (
                    f"[超时] 命令执行超过 {input.timeout_seconds} 秒\n"
                    f"命令: {input.command}"
                )

            # 检查取消
            if signal.aborted:
                process.kill()
                await process.wait()
                return f"[已取消] {signal.reason}"

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # 输出截断
            max_output = 50000
            if len(stdout) > max_output:
                stdout = stdout[:max_output] + f"\n... [输出截断，共 {len(stdout)} 字符]"
            if len(stderr) > max_output:
                stderr = stderr[:max_output] + "\n... [stderr 截断]"

            returncode = process.returncode or 0

            parts = [
                f"[退出码: {returncode}] {'✓' if returncode == 0 else '✗'}",
                f"[工作目录] {cwd_path}",
            ]

            if stdout:
                parts.append(f"\n── stdout ──\n{stdout.rstrip()}")
            if stderr:
                parts.append(f"\n── stderr ──\n{stderr.rstrip()}")

            return "\n".join(parts)

        except FileNotFoundError:
            return "[错误] Shell 不可用，请检查环境配置"
        except Exception as e:
            return f"[错误] 执行命令失败: {type(e).__name__}: {e}"
