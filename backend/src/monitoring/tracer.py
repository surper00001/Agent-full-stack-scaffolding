"""
LLM 监测模块（全开源方案）。

基于 LangFuse + OpenTelemetry 提供：
- LLM 调用链路追踪（Trace / Span）
- Token 用量与成本统计
- 响应延迟监控
- Agent 执行过程的完整可视化

LangFuse: 开源 LLM 可观测平台（https://github.com/langfuse/langfuse）
OpenTelemetry: 开放可观测标准，可对接 Jaeger/Tempo/Prometheus
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any

from loguru import logger

from src.core.config import Settings, get_settings


class _MonitoringManager:
    """
    监测管理器（单例）。

    根据配置自动选择 LangFuse 或 OpenTelemetry 作为后端，
    提供统一的追踪接口。
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._enabled = self._settings.monitoring_enabled
        self._provider = self._settings.monitoring_provider
        self._initialized = False

    def initialize(self) -> None:
        """初始化监测后端（在应用启动时调用）。"""
        if not self._enabled:
            logger.info("LLM 监测已禁用")
            return

        if self._provider == "langfuse":
            self._init_langfuse()
        elif self._provider == "otel":
            self._init_otel()
        else:
            logger.warning(f"未知的监测提供商: {self._provider}，跳过初始化")

        self._initialized = True

    def _init_langfuse(self) -> None:
        """初始化 LangFuse 客户端。"""
        public_key = self._settings.langfuse_public_key
        secret_key = (
            self._settings.langfuse_secret_key.get_secret_value()
            if self._settings.langfuse_secret_key
            else None
        )

        if not public_key or not secret_key:
            logger.warning("LangFuse 密钥未配置，LLM 监测将不启用")
            self._enabled = False
            return

        try:
            # 设置 LangChain 环境变量，LangFuse 会自动注入回调
            import os

            os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
            os.environ["LANGFUSE_SECRET_KEY"] = secret_key
            os.environ["LANGFUSE_HOST"] = self._settings.langfuse_host

            logger.info(f"LangFuse 监测已初始化 | host: {self._settings.langfuse_host}")
        except Exception as e:
            logger.error(f"LangFuse 初始化失败: {e}")
            self._enabled = False

    def _init_otel(self) -> None:
        """初始化 OpenTelemetry。"""
        endpoint = self._settings.otel_exporter_endpoint
        if not endpoint:
            logger.warning("OTEL 端点未配置，LLM 监测将不启用")
            self._enabled = False
            return

        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource(
                attributes={"service.name": self._settings.otel_service_name}
            )
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)

            logger.info(f"OpenTelemetry 监测已初始化 | endpoint: {endpoint}")
        except Exception as e:
            logger.error(f"OpenTelemetry 初始化失败: {e}")
            self._enabled = False

    @contextmanager
    def trace(
        self, name: str, metadata: dict[str, Any] | None = None
    ) -> Any:
        """
        创建追踪 Span 的上下文管理器。

        使用示例:
            with monitor.trace("agent_execute", {"agent_type": "chat"}) as span:
                result = await agent.run(input)

        注意: 这是一个轻量级包装，实际的 LangChain 回调
              由 LangFuse / OTEL 自动注入到 LLM 调用链中。
        """
        start = time.monotonic()
        span_data: dict[str, Any] = {
            "name": name,
            "metadata": metadata or {},
            "start_time": start,
        }
        try:
            yield span_data
        except Exception as e:
            span_data["error"] = str(e)
            span_data["status"] = "error"
            raise
        finally:
            span_data["duration_ms"] = (time.monotonic() - start) * 1000
            span_data["status"] = span_data.get("status", "ok")
            if self._enabled:
                logger.debug(
                    f"[trace] {name} | {span_data['duration_ms']:.0f}ms "
                    f"| status={span_data['status']}"
                )

    async def atrace(
        self, name: str, metadata: dict[str, Any] | None = None
    ) -> Any:
        """异步版本追踪，用法同 trace()，但允许在 async with 中使用。"""
        return self.trace(name, metadata)

    def is_enabled(self) -> bool:
        return self._enabled


# 全局单例
_monitor: _MonitoringManager | None = None


def get_monitor() -> _MonitoringManager:
    """获取监测管理器单例。"""
    global _monitor
    if _monitor is None:
        _monitor = _MonitoringManager()
    return _monitor


def setup_monitoring() -> None:
    """初始化监测系统（应用启动时调用）。"""
    get_monitor().initialize()
