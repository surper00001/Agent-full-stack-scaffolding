"""
WSL2 Docker Sandbox — Windows 宿主 + WSL2 Docker 隔离执行。

核心理念：
- Windows 宿主机通过 wsl 命令调用 WSL2 内的 Docker daemon
- 每个 Skill 执行创建一个临时容器，用完即焚
- 支持 CPU/内存/磁盘/网络限制

前置条件：
- Windows 11 + WSL2 已安装
- WSL2 发行版内 Docker 已安装并运行
- 或者 Docker Desktop with WSL2 backend

配置：
    wsl_distro: WSL2 发行版名称，默认从 wsl -l -q 自动获取
    docker_socket: Docker socket 路径，默认 /var/run/docker.sock
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, ClassVar

from loguru import logger

from src.harness.sandbox.base import (
    BaseSandbox,
    NetworkMode,
    SandboxConfig,
    SandboxResult,
    SandboxStatus,
)


class WSLDockerSandbox(BaseSandbox):
    """
    WSL2 Docker 沙箱。

    通过 wsl 命令桥接到 WSL2 内的 Docker，创建临时容器执行代码。

    执行流程：
        1. 生成唯一容器名
        2. 创建临时 workspace 目录
        3. docker run --rm -v workspace:/workspace --network=none ...
        4. 写入并执行代码
        5. docker stop + rm（确保清理）
    """

    # 基础 Python 镜像
    BASE_IMAGE: ClassVar[str] = "python:3.12-slim"

    # Docker 资源限制默认值
    DEFAULT_CPU: ClassVar[str] = "0.5"
    DEFAULT_MEMORY: ClassVar[str] = "256m"
    DEFAULT_DISK: ClassVar[str] = "512m"

    def __init__(self, config: SandboxConfig | None = None) -> None:
        super().__init__(config or SandboxConfig())
        self._container_id: str = ""
        self._container_name: str = ""
        self._workspace_host: Path | None = None
        self._id = f"docker-{id(self):x}"
        self._wsl_available = False
        self._docker_available = False

    # ── 生命周期 ──

    async def start(self) -> None:
        """检测 WSL + Docker 可用性，准备工作目录。"""
        # 检测 WSL
        self._wsl_available = await self._check_wsl()
        if not self._wsl_available:
            logger.warning("WSL2 不可用，DockerSandbox 将回退到 ProcessSandbox")
            self._status = SandboxStatus.FAILED
            return

        # 检测 Docker
        self._docker_available = await self._check_docker()
        if not self._docker_available:
            logger.warning("WSL2 内 Docker 不可用")
            self._status = SandboxStatus.FAILED
            return

        # 确保基础镜像存在
        await self._ensure_image()

        # 创建工作目录
        self._workspace_host = Path(tempfile.mkdtemp(prefix="wsl_sandbox_"))
        self._container_name = f"sandbox-{hashlib.sha1(self._id.encode()).hexdigest()[:12]}"

        self._status = SandboxStatus.IDLE
        logger.info(f"WSL Docker Sandbox {self._container_name} 就绪")

    async def execute_code(
        self,
        code: str,
        timeout_seconds: int | None = None,
        security_policy: Any | None = None,
    ) -> SandboxResult:
        if not self._wsl_available or not self._docker_available:
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr="WSL Docker Sandbox 不可用",
                duration_ms=0, sandbox_id=self._id,
            )

        self._status = SandboxStatus.BUSY
        self._execution_count += 1
        timeout = timeout_seconds or self.config.timeout_seconds
        start = time.perf_counter()

        try:
            # 统一安全扫描 — 委托给 CodeScanner + SecurityPolicy
            from src.harness.security.policies import SecurityPolicy, get_policy
            from src.harness.security.scanner import CodeScanner

            policy: SecurityPolicy = (
                security_policy if isinstance(security_policy, SecurityPolicy)
                else get_policy("medium")
            )
            scan_result = CodeScanner(policy).scan(code)
            if not scan_result.passed:
                errors_text = "\n".join(
                    f"  - [{f.severity}] L{f.line}: {f.message}" for f in scan_result.errors
                )
                return self._fail_result(
                    f"安全扫描未通过 (评分={scan_result.score}):\n{errors_text}", start
                )

            # 写入代码到 workspace
            if self._workspace_host:
                script = self._workspace_host / "exec.py"
                script.write_text(code, encoding="utf-8")

            # Docker exec
            result = await self._docker_exec(
                command="python /workspace/exec.py",
                timeout_seconds=timeout,
            )
            result.sandbox_id = self._id
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result

        except Exception as e:
            return self._fail_result(f"执行异常: {type(e).__name__}: {e}", start)
        finally:
            self._status = SandboxStatus.IDLE

    async def execute_command(
        self,
        command: str,
        timeout_seconds: int | None = None,
        working_dir: str = "/workspace",
    ) -> SandboxResult:
        if not self._wsl_available or not self._docker_available:
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr="WSL Docker Sandbox 不可用",
                duration_ms=0, sandbox_id=self._id,
            )

        self._status = SandboxStatus.BUSY
        self._execution_count += 1
        start = time.perf_counter()

        try:
            result = await self._docker_exec(
                command=f"cd {working_dir} && {command}",
                timeout_seconds=timeout_seconds or self.config.timeout_seconds,
            )
            result.sandbox_id = self._id
            result.duration_ms = (time.perf_counter() - start) * 1000
            return result
        except Exception as e:
            return self._fail_result(f"命令异常: {type(e).__name__}: {e}", start)
        finally:
            self._status = SandboxStatus.IDLE

    async def install_dependencies(self, packages: list[str]) -> SandboxResult:
        if not packages:
            return SandboxResult(exit_code=0, stdout="无依赖", stderr="", duration_ms=0)
        return await self.execute_command(f"pip install {' '.join(packages)}", timeout_seconds=120)

    async def health_check(self) -> bool:
        result = await self.execute_command("echo ok")
        return result.success and "ok" in result.stdout

    async def cleanup(self) -> None:
        # 强制清理 Docker 容器（防止进程崩溃后残留）
        if self._container_name:
            try:
                rm_cmd = self._wsl_wrap(f"docker rm -f {self._container_name}")
                proc = await asyncio.create_subprocess_exec(
                    *rm_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.wait()
            except Exception as e:
                logger.debug(f"Docker 清理容器 {self._container_name} 失败: {e}")

        if self._workspace_host and self._workspace_host.exists():
            try:
                shutil.rmtree(self._workspace_host, ignore_errors=True)
            except Exception as e:
                logger.debug(f"Docker 清理工作空间 {self._workspace_host} 失败: {e}")

    async def stop(self) -> None:
        self._status = SandboxStatus.TERMINATED
        await self.cleanup()

    def __del__(self) -> None:
        """析构兜底：进程崩溃时尽力清理容器。

        注意：析构函数中不能使用 loguru（解释器可能已部分销毁），
        因此仅静默忽略异常 —— 清理失败不会导致崩溃。
        """
        if self._container_name:
            try:
                import subprocess as _subprocess
                _subprocess.run(
                    ["wsl", "bash", "-c", f"docker rm -f {self._container_name}"],
                    capture_output=True, timeout=10,
                )
            except Exception:
                pass  # 析构函数：解释器可能已部分销毁，无法安全记录日志

    async def restart(self) -> None:
        await self.cleanup()
        await self.start()

    # ── 内部方法 ──

    async def _docker_exec(
        self,
        command: str,
        timeout_seconds: int = 60,
    ) -> SandboxResult:
        """在 Docker 容器内执行命令。"""
        import os as _os

        workspace = str(self._workspace_host) if self._workspace_host else "/tmp"

        # Windows 路径 → WSL 路径转换 (C:\Users\... → /mnt/c/Users/...)
        if _os.name == "nt" and ":" in workspace:
            drive = workspace[0].lower()
            rest = workspace[2:].replace("\\", "/")
            workspace = f"/mnt/{drive}{rest}"

        # 网络参数
        network_flag = {
            NetworkMode.NONE: "--network=none",
            NetworkMode.INTERNAL: "--network=bridge",
            NetworkMode.FULL: "--network=bridge",
        }.get(self.config.network, "--network=none")

        # 转义命令中的特殊字符，防止嵌套引号破坏 shell 解析
        # 例如 command="print('hello')" 中的引号会截断 sh -c "..." 的外层引号
        escaped = command.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
        docker_cmd = (
            f"docker run --rm "
            f"--name {self._container_name} "
            f"--cpus={self.config.cpu_limit or self.DEFAULT_CPU} "
            f"--memory={self.config.memory_mb or 256}m "
            f"--memory-swap={self.config.memory_mb or 256}m "
            f"--storage-opt size={self.config.disk_mb or 512}m "
            f"{network_flag} "
            f"--read-only={'true' if self.config.read_only_rootfs else 'false'} "
            f"-v {workspace}:/workspace "
            f"-w /workspace "
            f"{self.BASE_IMAGE} "
            f"sh -c \"{escaped}\""
        )

        # 通过 WSL 执行
        full_cmd = self._wsl_wrap(docker_cmd)

        try:
            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds + 10,
                )
                killed = False
            except TimeoutError:
                # 强制停止容器
                self._status = SandboxStatus.BUSY
                stop_cmd = self._wsl_wrap(f"docker stop -t 5 {self._container_name}")
                stop_process = await asyncio.create_subprocess_exec(*stop_cmd)
                await stop_process.wait()
                killed = True
                stdout_bytes, stderr_bytes = b"", f"执行超时 ({timeout_seconds}s)，容器已强制停止".encode()

            stdout = stdout_bytes.decode("utf-8", errors="replace")[:50000]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:50000]

            truncated = len(stdout) > 50000 or len(stderr) > 50000

            return SandboxResult(
                exit_code=process.returncode or (-1 if killed else 0),
                stdout=stdout,
                stderr=stderr,
                duration_ms=0,
                truncated=truncated,
                killed=killed,
            )

        except FileNotFoundError:
            return SandboxResult(
                exit_code=-1, stdout="",
                stderr="wsl 命令不可用，请确保 WSL2 已安装",
                duration_ms=0,
            )

    def _wsl_wrap(self, command: str) -> list[str]:
        """将 Docker 命令包装为 WSL 调用。"""
        return ["wsl", "bash", "-c", command]

    async def _check_wsl(self) -> bool:
        """检测 WSL 是否可用。"""
        try:
            result = await asyncio.create_subprocess_exec(
                "wsl", "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await result.communicate()
            return result.returncode == 0 if result.returncode is not None else False
        except FileNotFoundError:
            return False

    async def _check_docker(self) -> bool:
        """检测 WSL 内 Docker 是否可用。"""
        try:
            process = await asyncio.create_subprocess_exec(
                "wsl", "bash", "-c", "docker info --format '{{.ServerVersion}}'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            return process.returncode == 0 if process.returncode is not None else bool(stdout.strip())
        except Exception as e:
            logger.debug(f"Docker 检测失败: {e}")
            return False

    async def _ensure_image(self) -> None:
        """确保基础镜像存在，不存在则拉取。"""
        try:
            process = await asyncio.create_subprocess_exec(
                "wsl", "bash", "-c",
                f"docker image inspect {self.BASE_IMAGE} --format 'ok'",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await process.communicate()
            if b"ok" not in (stdout or b""):
                logger.info(f"拉取 Docker 镜像: {self.BASE_IMAGE}...")
                pull = await asyncio.create_subprocess_exec(
                    "wsl", "bash", "-c", f"docker pull {self.BASE_IMAGE}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await pull.wait()
        except Exception as e:
            logger.warning(f"镜像检查失败: {e}")

    def _fail_result(self, msg: str, start: float) -> SandboxResult:
        return SandboxResult(
            exit_code=1,
            stdout="",
            stderr=msg,
            duration_ms=(time.perf_counter() - start) * 1000,
            sandbox_id=self._id,
        )
