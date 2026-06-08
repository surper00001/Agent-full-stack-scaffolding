"""
Sandbox Manager — 沙箱池管理器。

管理多个沙箱实例的生命周期：
- 预创建沙箱池（加速冷启动）
- 健康检查 + 自动恢复
- 按需分配 / 释放
- 优雅关闭清理
- 自动降级（Docker → Process）
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from loguru import logger

from src.harness.sandbox.base import (
    BaseSandbox,
    NetworkMode,
    SandboxConfig,
    SandboxResult,
    SandboxStatus,
)
from src.harness.sandbox.process_sandbox import ProcessSandbox
from src.harness.sandbox.wsl_docker_sandbox import WSLDockerSandbox


@dataclass
class PoolConfig:
    """沙箱池配置。"""
    pool_size: int = 3               # 预创建沙箱数量
    max_pool_size: int = 10          # 最大沙箱数量
    sandbox_ttl_seconds: int = 300   # 沙箱最大存活时间（5分钟后重建）
    health_check_interval: int = 30  # 健康检查间隔（秒）
    default_timeout: int = 60        # 默认执行超时
    prefer_docker: bool = True       # 是否优先使用 Docker


class SandboxManager:
    """
    沙箱池管理器。

    使用方式：
        manager = SandboxManager()
        await manager.start()

        async with manager.acquire() as sandbox:
            result = await sandbox.execute_code("print('hello')")

        await manager.shutdown()
    """

    def __init__(self, config: PoolConfig | None = None) -> None:
        self._config = config or PoolConfig()
        self._pool: list[BaseSandbox] = []
        self._in_use: set[str] = set()
        self._available = asyncio.Semaphore(self._config.pool_size)
        self._running = False
        self._health_task: asyncio.Task | None = None
        self._docker_available = False

        # 统计
        self._total_created = 0
        self._total_acquired = 0
        self._total_failed = 0

    async def start(self) -> None:
        """启动沙箱管理器。"""
        self._running = True

        # 检测 Docker 可用性（含功能验证）
        self._docker_available = await self._probe_docker()
        logger.info(
            f"沙箱管理器启动: Docker={'可用' if self._docker_available else '不可用'}"
            f"{'，回退到 ProcessSandbox' if not self._docker_available else ''}"
        )

        # 预创建沙箱池
        create_count = self._config.pool_size if self._docker_available and self._config.prefer_docker else 2
        for i in range(create_count):
            sandbox = await self._create_sandbox(f"pool-{i}")
            if sandbox and sandbox.status != SandboxStatus.FAILED:
                self._pool.append(sandbox)

        logger.info(f"沙箱池已就绪: {len(self._pool)}/{create_count} 个沙箱")

        # 启动健康检查
        self._health_task = asyncio.create_task(self._health_loop())

    async def shutdown(self) -> None:
        """关闭所有沙箱。"""
        self._running = False

        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        for sandbox in self._pool:
            try:
                await sandbox.stop()
            except Exception as e:
                logger.warning(f"沙箱关闭失败 [{sandbox._id}]: {e}")

        self._pool.clear()
        self._in_use.clear()
        logger.info("沙箱管理器已关闭")

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[BaseSandbox]:
        """获取一个沙箱（上下文管理器）。"""
        await self._available.acquire()
        sandbox = None

        try:
            sandbox = await self._get_or_create()
            self._in_use.add(sandbox._id)
            self._total_acquired += 1
            yield sandbox
        except Exception:
            self._total_failed += 1
            raise
        finally:
            if sandbox:
                self._in_use.discard(sandbox._id)
                # 检查沙箱是否需要重建
                if sandbox.age_seconds > self._config.sandbox_ttl_seconds:
                    try:
                        await sandbox.stop()
                    except Exception:
                        logger.debug(f"沙箱 {sandbox._id} 已过期，停止时出错（忽略）")
                    sandbox = await self._create_sandbox("recycled")
                if sandbox and sandbox.status != SandboxStatus.FAILED:
                    self._pool.append(sandbox)

            self._available.release()

    async def execute_code(
        self, code: str, timeout: int | None = None, security_policy: Any | None = None
    ) -> SandboxResult:
        """快捷方法：获取沙箱 → 执行代码 → 自动释放。"""
        async with self.acquire() as sandbox:
            return await sandbox.execute_code(
                code, timeout or self._config.default_timeout, security_policy=security_policy
            )

    async def execute_command(self, command: str, timeout: int | None = None) -> SandboxResult:
        """快捷方法：获取沙箱 → 执行命令 → 自动释放。"""
        async with self.acquire() as sandbox:
            return await sandbox.execute_command(command, timeout or self._config.default_timeout)

    # ── 内部 ──

    async def _get_or_create(self) -> BaseSandbox:
        """从池中获取或创建新沙箱。"""
        # 从池中取一个健康的
        while self._pool:
            sandbox = self._pool.pop()
            if sandbox.status == SandboxStatus.FAILED:
                continue
            try:
                healthy = await sandbox.health_check()
                if healthy:
                    return sandbox
                else:
                    await sandbox.stop()
            except Exception:
                logger.debug(f"沙箱 {sandbox._id} 健康检查失败，正在停止")
                await sandbox.stop()

        # 池空，创建新的
        if len(self._in_use) < self._config.max_pool_size:
            sandbox = await self._create_sandbox("on-demand")
            if sandbox and sandbox.status != SandboxStatus.FAILED:
                return sandbox

        # 等待池中释放
        logger.warning("沙箱池已满，等待释放...")
        await asyncio.sleep(1)
        return await self._get_or_create()

    async def _probe_docker(self) -> bool:
        """检测 Docker 是否可用（含功能验证）。"""
        try:
            docker = WSLDockerSandbox()
            await docker.start()
            if docker.status == SandboxStatus.FAILED:
                return False
            # 功能验证：尝试执行简单命令
            result = await docker.execute_code("print('ok')", timeout_seconds=10)
            await docker.stop()
            return result.success
        except Exception as e:
            logger.debug(f"Docker 探测失败: {e}")
            return False

    async def _create_sandbox(self, label: str) -> BaseSandbox | None:
        """创建一个新的沙箱实例。"""
        config = SandboxConfig(
            timeout_seconds=self._config.default_timeout,
            network=NetworkMode.NONE,
        )

        if self._docker_available and self._config.prefer_docker:
            sandbox: BaseSandbox = WSLDockerSandbox(config)
        else:
            sandbox = ProcessSandbox(config)

        try:
            await sandbox.start()
            self._total_created += 1
            return sandbox
        except Exception as e:
            logger.error(f"创建沙箱失败 ({label}): {e}")
            return None

    async def _health_loop(self) -> None:
        """定期健康检查。"""
        while self._running:
            await asyncio.sleep(self._config.health_check_interval)
            dead_count = 0
            for i in range(len(self._pool) - 1, -1, -1):
                sandbox = self._pool[i]
                try:
                    healthy = await sandbox.health_check()
                    if not healthy:
                        await sandbox.stop()
                        self._pool.pop(i)
                        dead_count += 1
                except Exception:
                    logger.debug(f"沙箱 {self._pool[i]._id} 健康检查异常，从池中移除")
                    self._pool.pop(i)
                    dead_count += 1

            if dead_count:
                logger.debug(f"健康检查: 移除 {dead_count} 个不健康的沙箱")

            # 补充池
            while len(self._pool) < self._config.pool_size:
                sandbox = await self._create_sandbox("auto-replenish")
                if sandbox:
                    self._pool.append(sandbox)
                else:
                    break

    @property
    def stats(self) -> dict:
        return {
            "pool_size": len(self._pool),
            "in_use": len(self._in_use),
            "total_created": self._total_created,
            "total_acquired": self._total_acquired,
            "total_failed": self._total_failed,
            "docker_available": self._docker_available,
        }


# 全局单例
_sandbox_manager: SandboxManager | None = None


def get_sandbox_manager() -> SandboxManager:
    """获取全局沙箱管理器单例。"""
    global _sandbox_manager
    if _sandbox_manager is None:
        _sandbox_manager = SandboxManager()
    return _sandbox_manager


async def init_sandbox_manager() -> SandboxManager:
    """初始化并启动全局沙箱管理器。"""
    manager = get_sandbox_manager()
    await manager.start()
    return manager


async def shutdown_sandbox_manager() -> None:
    """关闭全局沙箱管理器。"""
    global _sandbox_manager
    if _sandbox_manager:
        await _sandbox_manager.shutdown()
        _sandbox_manager = None
