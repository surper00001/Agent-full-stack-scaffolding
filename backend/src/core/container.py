"""
轻量级 DI 容器 — 统一管理核心服务单例的生命周期。

设计目标：
- 将分散的模块级单例（16+ 种不一致模式）统一为集中管理
- 支持延迟初始化 + 优雅关闭
- 向后兼容：现有 get_xxx_service() 函数继续工作
- 测试友好：提供 reset() 用于隔离测试

使用方式：
    container = ServiceContainer()
    await container.init()

    # 访问服务（带类型提示）
    embedding = container.embedding_service
    llm = container.llm_factory

    await container.shutdown()
"""

from __future__ import annotations

import threading
from typing import Any

from loguru import logger


class _LazyService:
    """单个服务的延迟加载包装器。"""

    def __init__(self, factory, name: str = ""):
        self._factory = factory
        self._instance: Any = None
        self._lock = threading.Lock()
        self._name = name

    def get(self) -> Any:
        """获取服务实例（双重检查锁定）。"""
        if self._instance is not None:
            return self._instance
        with self._lock:
            if self._instance is None:
                self._instance = self._factory()
                logger.debug(f"ServiceContainer: 已初始化 {self._name}")
        return self._instance

    async def get_async(self) -> Any:
        """异步获取服务实例。"""
        if self._instance is not None:
            return self._instance
        result = self._factory()
        if hasattr(result, "__await__"):
            result = await result
        with self._lock:
            if self._instance is None:
                self._instance = result
        return self._instance

    def reset(self) -> None:
        """重置服务实例（用于测试）。"""
        self._instance = None

    @property
    def is_initialized(self) -> bool:
        return self._instance is not None


class ServiceContainer:
    """
    核心服务容器。

    统一管理所有有状态服务的生命周期。
    每个服务通过 _LazyService 包装器延迟初始化。

    使用示例：
        container = ServiceContainer()

        # 可选：添加自定义实现（测试用）
        container.register("embedding_service", mock_embedding)

        await container.init()  # 预初始化关键服务
        await container.shutdown()  # 优雅关闭
    """

    def __init__(self) -> None:
        # ── 核心服务注册 ──
        self._services: dict[str, _LazyService] = {
            "embedding_service": _LazyService(self._create_embedding_service, "EmbeddingService"),
            "reranker_service": _LazyService(self._create_reranker_service, "RerankerService"),
            "llm_factory": _LazyService(self._create_llm_factory, "LLMFactory"),
            "tool_registry": _LazyService(self._create_tool_registry, "UnifiedToolRegistry"),
            "vlm_service": _LazyService(self._create_vlm_service, "VLMService"),
            "monitor": _LazyService(self._create_monitor, "Monitor"),
            "metrics": _LazyService(self._create_metrics, "Metrics"),
            "context_store": _LazyService(self._create_context_store, "ConversationContextStore"),
            "sandbox_manager": _LazyService(self._create_sandbox_manager, "SandboxManager"),
            "checkpointer": _LazyService(self._create_checkpointer, "Checkpointer"),
        }
        self._initialized = False
        self._lock = threading.Lock()

    # ── 工厂方法 ──

    @staticmethod
    def _create_embedding_service():
        from src.services.embedding_service import get_embedding_service
        return get_embedding_service()

    @staticmethod
    def _create_reranker_service():
        from src.services.reranker_service import get_reranker_service
        return get_reranker_service()

    @staticmethod
    def _create_llm_factory():
        from src.llm.factory import get_llm_factory
        return get_llm_factory()

    @staticmethod
    def _create_tool_registry():
        from src.harness.unified_registry import get_unified_registry
        return get_unified_registry()

    @staticmethod
    def _create_vlm_service():
        from src.services.vlm_service import get_vlm_service
        return get_vlm_service()

    @staticmethod
    def _create_monitor():
        from src.monitoring.tracer import get_monitor
        return get_monitor()

    @staticmethod
    def _create_metrics():
        from src.monitoring.metrics import get_metrics
        return get_metrics()

    @staticmethod
    def _create_context_store():
        from src.services.conversation_context_store import get_conversation_context_store
        return get_conversation_context_store()

    @staticmethod
    def _create_sandbox_manager():
        from src.harness.sandbox.manager import get_sandbox_manager
        return get_sandbox_manager()

    @staticmethod
    def _create_checkpointer():
        from src.agents.checkpointer import get_checkpointer
        return get_checkpointer()

    # ── 公共 API ──

    async def init(self, services: list[str] | None = None) -> None:
        """
        预初始化指定服务（或所有服务）。

        在应用启动时调用，避免首次请求的冷启动延迟。
        """
        with self._lock:
            if self._initialized:
                return
            self._initialized = True

        names = services or list(self._services.keys())
        for name in names:
            svc = self._services.get(name)
            if svc and not svc.is_initialized:
                try:
                    await svc.get_async()
                except Exception as e:
                    logger.warning(f"ServiceContainer: {name} 初始化失败: {e}")

        logger.info(f"ServiceContainer: 已初始化 {sum(1 for s in self._services.values() if s.is_initialized)} 个服务")

    async def shutdown(self) -> None:
        """优雅关闭所有已初始化的服务。"""
        shutdown_order = [
            "sandbox_manager",   # 先关闭沙箱
            "context_store",
            "checkpointer",
        ]

        for name in shutdown_order:
            svc = self._services.get(name)
            if svc and svc.is_initialized:
                instance = svc.get()
                if hasattr(instance, "shutdown"):
                    try:
                        result = instance.shutdown()
                        if hasattr(result, "__await__"):
                            await result
                        logger.debug(f"ServiceContainer: {name} 已关闭")
                    except Exception as e:
                        logger.warning(f"ServiceContainer: {name} 关闭失败: {e}")

    def register(self, name: str, instance: Any) -> None:
        """
        手动注册一个服务实例（测试用）。

        用于注入 mock 或替换默认实现。
        """
        if name in self._services:
            self._services[name]._instance = instance
        else:
            svc = _LazyService(lambda: instance, name)
            svc._instance = instance
            self._services[name] = svc

    def reset(self) -> None:
        """重置所有服务（测试隔离用）。"""
        for svc in self._services.values():
            svc.reset()
        self._initialized = False

    def resolve(self, name: str) -> Any:
        """
        按名称获取服务实例。

        Raises:
            KeyError: 如果服务未注册
        """
        svc = self._services.get(name)
        if svc is None:
            raise KeyError(f"ServiceContainer: 未注册的服务 '{name}'。可用: {list(self._services.keys())}")
        return svc.get()

    # ── 属性快捷访问 ──

    @property
    def embedding_service(self):
        return self._services["embedding_service"].get()

    @property
    def reranker_service(self):
        return self._services["reranker_service"].get()

    @property
    def llm_factory(self):
        return self._services["llm_factory"].get()

    @property
    def tool_registry(self):
        return self._services["tool_registry"].get()

    @property
    def vlm_service(self):
        return self._services["vlm_service"].get()

    @property
    def monitor(self):
        return self._services["monitor"].get()

    @property
    def metrics(self):
        return self._services["metrics"].get()

    @property
    def context_store(self):
        return self._services["context_store"].get()

    @property
    def sandbox_manager(self):
        return self._services["sandbox_manager"].get()

    @property
    def checkpointer(self):
        return self._services["checkpointer"].get()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def initialized_count(self) -> int:
        return sum(1 for s in self._services.values() if s.is_initialized)


# ── 全局容器单例 ──

_container: ServiceContainer | None = None
_container_lock = threading.Lock()


def get_container() -> ServiceContainer:
    """获取全局 ServiceContainer 单例。"""
    global _container
    if _container is None:
        with _container_lock:
            if _container is None:
                _container = ServiceContainer()
    return _container


async def init_container(services: list[str] | None = None) -> ServiceContainer:
    """初始化全局容器（应用启动时调用）。"""
    container = get_container()
    await container.init(services)
    return container


async def shutdown_container() -> None:
    """关闭全局容器（应用停止时调用）。"""
    global _container
    if _container:
        await _container.shutdown()
        _container = None


def reset_container() -> None:
    """重置全局容器（测试用）。"""
    global _container
    if _container:
        _container.reset()
    _container = None
