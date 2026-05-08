"""
LLM 监测模块 — Langfuse + OpenTelemetry。

使用 Langfuse 的 LangChain CallbackHandler 自动追踪：
- LLM 调用（model、token、cost）
- Agent 执行链路（Plan → ReAct → Tools）
- 会话分组（session_id）与用户归因（user_id）
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from typing import Any

from loguru import logger

from src.core.config import Settings, get_settings


class _MonitoringManager:
    """监测管理器（单例）— 按配置选择 Langfuse 或 OpenTelemetry。"""

    def __init__(self) -> None:
        self._settings = get_settings()
        self._enabled = self._settings.monitoring_enabled
        self._provider = self._settings.monitoring_provider
        self._initialized = False
        self._langfuse_handler: Any = None

    def initialize(self) -> None:
        """初始化监测后端（应用启动时调用）。"""
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
        """初始化 Langfuse CallbackHandler（LangChain 集成）。

        Langfuse v2 通过环境变量读取凭证，因此先设置环境变量再创建 Handler。
        per-request 的 session_id/user_id/tags 通过 LangGraph config metadata 传入，
        CallbackHandler 的 _parse_langfuse_trace_attributes 会自动解析：
          - metadata["langfuse_session_id"] → session_id
          - metadata["langfuse_user_id"]   → user_id
          - metadata["langfuse_tags"]      → tags
        """
        public_key = self._settings.langfuse_public_key
        secret_key = (
            self._settings.langfuse_secret_key.get_secret_value()
            if self._settings.langfuse_secret_key
            else None
        )

        if not public_key or not secret_key:
            logger.warning("Langfuse 密钥未配置，LLM 监测将不启用")
            self._enabled = False
            return

        try:
            import os

            os.environ["LANGFUSE_PUBLIC_KEY"] = public_key
            os.environ["LANGFUSE_SECRET_KEY"] = secret_key
            os.environ["LANGFUSE_HOST"] = self._settings.langfuse_host

            from langfuse.langchain import CallbackHandler

            self._langfuse_handler = CallbackHandler()

            logger.info(
                f"Langfuse 监测已初始化 | host: {self._settings.langfuse_host}"
            )
        except Exception as e:
            logger.error(f"Langfuse 初始化失败: {e}")
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

    @property
    def langfuse_handler(self) -> Any | None:
        """获取 Langfuse LangChain CallbackHandler（供 Agent/LLM 注入）。"""
        return self._langfuse_handler

    def is_enabled(self) -> bool:
        return self._enabled and self._langfuse_handler is not None

    @contextmanager
    def trace(
        self, name: str, metadata: dict[str, Any] | None = None
    ) -> Any:
        """轻量级手动 Span（仅用于非 LangChain 代码段）。"""
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
        return self.trace(name, metadata)

    def flush(self) -> None:
        """确保所有追踪数据已发送（进程退出前调用）。"""
        if self._langfuse_handler is not None:
            try:
                self._langfuse_handler.flush()
            except Exception:
                pass


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
