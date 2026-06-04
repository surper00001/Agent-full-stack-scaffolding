"""
Process Sandbox — 子进程沙箱实现。

轻量级沙箱，用于开发环境。不需要 Docker，通过 subprocess 隔离执行。

安全限制：
- 独立工作目录（临时目录）
- 环境变量隔离
- 超时控制
- 输出截断
- AST 白名单 Python 代码执行（仅 execute_code）
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
from pathlib import Path
from typing import ClassVar

from loguru import logger

from src.harness.sandbox.base import (
    BaseSandbox,
    NetworkMode,
    SandboxConfig,
    SandboxResult,
    SandboxStatus,
)


class ProcessSandbox(BaseSandbox):
    """
    子进程沙箱。

    每个实例使用独立的临时目录作为工作空间。
    适合开发和测试，不需要 Docker 环境。
    """

    # 禁止的模块/函数（AST 级别）
    _FORBIDDEN_MODULES: ClassVar[set[str]] = {
        "os", "subprocess", "shutil", "socket", "ctypes",
        "importlib", "sys", "builtins", "__builtins__",
        "compile", "eval", "exec", "open",
    }

    # 沙箱白名单环境变量（仅这些变量会传递给子进程）
    _ALLOWED_ENV: ClassVar[set[str]] = {
        # 系统路径
        "PATH", "PATHEXT", "SystemRoot", "SYSTEMROOT",
        # Python 运行时
        "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8",
        "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
        # 标准环境
        "TEMP", "TMP", "TMPDIR",
        "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH",
        "USER", "USERNAME", "LOGNAME",
        "LANG", "LC_ALL", "LC_CTYPE",
        # 代理（如果沙箱需要网络，可使用白名单代理地址）
        # "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        # 虚拟环境（如需在沙箱中复用 venv）
        "VIRTUAL_ENV", "PIP_REQUIRE_VIRTUALENV",
        # 系统架构
        "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
        "OS", "COMSPEC",
    }

    # 允许的 safe 模块
    _ALLOWED_MODULES: ClassVar[set[str]] = {
        "json", "math", "statistics", "datetime", "collections",
        "itertools", "functools", "re", "string", "textwrap",
        "hashlib", "base64", "binascii", "uuid",
        "typing", "dataclasses", "enum",
        "csv", "html", "xml.etree.ElementTree", "urllib.parse",
        "random", "secrets", "pathlib",
        "requests", "httpx",  # 网络请求（受限于沙箱网络策略）
    }

    def __init__(self, config: SandboxConfig | None = None) -> None:
        super().__init__(config or SandboxConfig())
        self._workspace: Path | None = None
        self._id = f"proc-{id(self):x}"

    @classmethod
    def _build_sandbox_env(cls, workspace: str) -> dict[str, str]:
        """构建沙箱最小化环境变量（仅白名单变量透传，防止密钥泄露）。"""
        env: dict[str, str] = {}
        for key, value in os.environ.items():
            if key in cls._ALLOWED_ENV or key.startswith("CONDA_") or key.startswith("UV_"):
                env[key] = value
        env["PYTHONPATH"] = workspace
        return env

    async def start(self) -> None:
        self._workspace = Path(tempfile.mkdtemp(prefix="sandbox_"))
        self._status = SandboxStatus.IDLE
        logger.debug(f"ProcessSandbox {self._id} 已启动: {self._workspace}")

    async def execute_code(
        self,
        code: str,
        timeout_seconds: int | None = None,
    ) -> SandboxResult:
        if not self._workspace:
            return SandboxResult(
                exit_code=-1, stdout="", stderr="沙箱未启动",
                duration_ms=0, sandbox_id=self._id,
            )

        self._status = SandboxStatus.BUSY
        self._execution_count += 1
        timeout = timeout_seconds or self.config.timeout_seconds
        start = time.perf_counter()

        try:
            # AST 安全检查
            ast_errors = _check_code_safety(code)
            if ast_errors:
                return SandboxResult(
                    exit_code=1, stdout="",
                    stderr=f"安全扫描未通过:\n" + "\n".join(f"  - {e}" for e in ast_errors),
                    duration_ms=(time.perf_counter() - start) * 1000,
                    sandbox_id=self._id,
                )

            # 通过子进程执行
            script_path = self._workspace / "_exec.py"
            script_path.write_text(code, encoding="utf-8")

            process = await asyncio.create_subprocess_exec(
                "python", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._workspace),
                env=self._build_sandbox_env(str(self._workspace)),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout,
                )
                killed = False
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                stdout_bytes, stderr_bytes = b"", f"执行超时 ({timeout}s)".encode()
                killed = True

            elapsed = (time.perf_counter() - start) * 1000
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            # 输出截断
            max_out = 50000
            truncated = len(stdout) > max_out or len(stderr) > max_out
            stdout = stdout[:max_out] + ("\n... [截断]" if len(stdout) > max_out else "")
            stderr = stderr[:max_out] + ("\n... [截断]" if len(stderr) > max_out else "")

            return SandboxResult(
                exit_code=process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                duration_ms=elapsed,
                truncated=truncated,
                killed=killed,
                sandbox_id=self._id,
            )

        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr=f"沙箱执行异常: {type(e).__name__}: {e}",
                duration_ms=elapsed,
                sandbox_id=self._id,
            )
        finally:
            self._status = SandboxStatus.IDLE

    async def execute_command(
        self,
        command: str,
        timeout_seconds: int | None = None,
        working_dir: str = "/workspace",
    ) -> SandboxResult:
        if not self._workspace:
            return SandboxResult(
                exit_code=-1, stdout="", stderr="沙箱未启动",
                duration_ms=0, sandbox_id=self._id,
            )

        self._status = SandboxStatus.BUSY
        self._execution_count += 1
        timeout = timeout_seconds or self.config.timeout_seconds
        cwd = self._workspace if working_dir == "/workspace" else Path(working_dir)
        start = time.perf_counter()

        try:
            process = await asyncio.create_subprocess_exec(
                "cmd", "/c", command if os.name == "nt" else command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd.exists() else str(self._workspace),
                env=self._build_sandbox_env(str(self._workspace)),
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout,
                )
                killed = False
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                stdout_bytes = b""
                stderr_bytes = f"命令超时 ({timeout}s)".encode()
                killed = True

            elapsed = (time.perf_counter() - start) * 1000
            stdout = stdout_bytes.decode("utf-8", errors="replace")[:50000]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:50000]

            return SandboxResult(
                exit_code=process.returncode or 0,
                stdout=stdout,
                stderr=stderr,
                duration_ms=elapsed,
                killed=killed,
                sandbox_id=self._id,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr=f"命令执行异常: {type(e).__name__}: {e}",
                duration_ms=elapsed,
                sandbox_id=self._id,
            )
        finally:
            self._status = SandboxStatus.IDLE

    async def install_dependencies(self, packages: list[str]) -> SandboxResult:
        if not packages:
            return SandboxResult(exit_code=0, stdout="无依赖需要安装", stderr="", duration_ms=0)
        return await self.execute_command(f"pip install {' '.join(packages)}")

    async def health_check(self) -> bool:
        try:
            result = await self.execute_command("echo ok")
            return result.success and "ok" in result.stdout
        except Exception:
            return False

    async def cleanup(self) -> None:
        if self._workspace and self._workspace.exists():
            import shutil
            try:
                shutil.rmtree(self._workspace, ignore_errors=True)
                logger.debug(f"ProcessSandbox {self._id} 已清理")
            except Exception as e:
                logger.warning(f"ProcessSandbox 清理失败: {e}")

    async def stop(self) -> None:
        self._status = SandboxStatus.TERMINATED
        await self.cleanup()

    async def restart(self) -> None:
        await self.cleanup()
        await self.start()


# ── AST 安全扫描 ──

def _check_code_safety(code: str) -> list[str]:
    """检查代码是否包含危险操作。"""
    import ast

    errors: list[str] = []

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"语法错误: {e}"]

    class SafetyVisitor(ast.NodeVisitor):
        def visit_Import(self, node: ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in ProcessSandbox._FORBIDDEN_MODULES:
                    errors.append(f"禁止导入模块: {alias.name}")
                    # 检查是否在白名单中
                    if alias.name in ProcessSandbox._ALLOWED_MODULES:
                        errors.pop()  # 允许
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom):
            if node.module:
                if node.module.split(".")[0] in ProcessSandbox._FORBIDDEN_MODULES:
                    if node.module not in ProcessSandbox._ALLOWED_MODULES:
                        errors.append(f"禁止从模块导入: {node.module}")
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            # 禁止 eval/exec/compile/open 直接调用
            if isinstance(node.func, ast.Name):
                if node.func.id in ("eval", "exec", "compile"):
                    errors.append(f"禁止调用: {node.func.id}()")
                if node.func.id == "open":
                    errors.append(f"禁止直接调用 open()，请使用文件工具")
            # 禁止 __import__
            if isinstance(node.func, ast.Attribute):
                if node.func.attr == "__import__":
                    errors.append("禁止调用 __import__()")
            self.generic_visit(node)

    SafetyVisitor().visit(tree)
    return errors
