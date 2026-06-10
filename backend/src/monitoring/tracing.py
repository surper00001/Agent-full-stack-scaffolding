"""
OpenTelemetry 分布式追踪初始化。

配置 OTLP 导出（gRPC/HTTP）、FastAPI/SQLAlchemy/Redis 自动埋点，
并将 trace_id / span_id 注入日志上下文。
"""

from __future__ import annotations

import logging
import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter as GRPCExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter as HTTPExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased

from src.core.config import get_settings

logger = logging.getLogger(__name__)

_tracing_initialized = False


def setup_tracing(
    app,
    service_name: str = "agent-platform",
    service_version: str = "0.1.0",
) -> None:
    """初始化 OpenTelemetry 分布式追踪。

    通过环境变量控制：
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP 收集器地址（不设置则禁用追踪）
    - OTEL_EXPORTER_PROTOCOL: "grpc"（默认）或 "http/protobuf"
    - OTEL_SAMPLE_RATIO: 采样率（默认 0.1，即 10%）

    使用示例（docker-compose）:
        OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
    """
    global _tracing_initialized
    if _tracing_initialized:
        return

    get_settings()
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")

    if not endpoint:
        logger.info("OpenTelemetry 追踪未启用（OTEL_EXPORTER_OTLP_ENDPOINT 未设置）")
        return

    try:
        # 资源标识
        resource = Resource.create({
            SERVICE_NAME: service_name,
            SERVICE_VERSION: service_version,
            "deployment.environment": os.environ.get("ENVIRONMENT", "development"),
        })

        # 采样率
        sample_ratio = float(os.environ.get("OTEL_SAMPLE_RATIO", "0.1"))

        # Provider + Exporter
        provider = TracerProvider(
            resource=resource,
            sampler=TraceIdRatioBased(sample_ratio),
        )

        protocol = os.environ.get("OTEL_EXPORTER_PROTOCOL", "grpc")
        if protocol == "http/protobuf":
            exporter = HTTPExporter(endpoint=endpoint)
        else:
            exporter = GRPCExporter(endpoint=endpoint)

        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)

        # 自动埋点
        FastAPIInstrumentor().instrument_app(app)
        SQLAlchemyInstrumentor().instrument(
            enable_commenter=True,
            commenter_options={"opentelemetry_values": True},
        )
        RedisInstrumentor().instrument()

        _tracing_initialized = True
        logger.info(
            f"OpenTelemetry 追踪已启用: endpoint={endpoint}, "
            f"protocol={protocol}, sample_ratio={sample_ratio}"
        )

    except Exception as e:
        logger.warning(f"OpenTelemetry 追踪初始化失败（不影响主流程）: {e}")


def get_tracer() -> trace.Tracer:
    """Get the OpenTelemetry tracer for manual instrumentation."""
    return trace.get_tracer(__name__)


def get_current_trace_context() -> dict[str, str]:
    """获取当前 span 的 trace_id / span_id（用于注入日志）。"""
    span = trace.get_current_span()
    if span and span.get_span_context().is_valid:
        ctx = span.get_span_context()
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
        }
    return {}
