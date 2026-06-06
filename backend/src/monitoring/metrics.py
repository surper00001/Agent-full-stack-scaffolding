"""
指标收集模块。

记录 Agent 平台的运行时指标，支持在内存查询和 Prometheus 格式导出：

- 请求计数与延迟
- Agent 执行次数与成功率
- LLM Token 消耗
- 向量数据库查询性能

轻量级 MetricsCollector 保留用于代码内查询；
Prometheus Counter/Histogram 用于 /metrics 端点导出。
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from prometheus_client import REGISTRY, Counter, Gauge, Histogram, generate_latest

# ── Prometheus 指标定义 ──

REQUEST_COUNT = Counter(
    "app_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status"],
)

REQUEST_LATENCY = Histogram(
    "app_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

AGENT_EXECUTIONS = Counter(
    "agent_executions_total",
    "Total number of agent executions",
    ["agent_type", "status"],
)

AGENT_EXECUTION_LATENCY = Histogram(
    "agent_execution_latency_seconds",
    "Agent execution latency in seconds",
    ["agent_type"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

LLM_TOKEN_USAGE = Counter(
    "llm_tokens_total",
    "Total LLM token usage",
    ["model", "type"],  # type = prompt | completion
)

LLM_CALL_LATENCY = Histogram(
    "llm_call_latency_seconds",
    "LLM API call latency in seconds",
    ["model"],
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

VECTOR_DB_QUERY_LATENCY = Histogram(
    "vector_db_query_latency_seconds",
    "Vector database query latency in seconds",
    ["operation", "store_type"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

ACTIVE_CONNECTIONS = Gauge(
    "app_active_connections",
    "Number of active connections (DB pool, Redis)",
    ["type"],
)

DB_POOL_SIZE = Gauge(
    "app_db_pool_size",
    "Database connection pool usage",
    ["state"],  # checked_out / overflow / total
)


def get_prometheus_metrics() -> bytes:
    """生成 Prometheus 格式的指标文本（供 /metrics 端点使用）。"""
    return generate_latest(REGISTRY)


# ── 兼容旧 MetricsCollector（保留内存查询能力）──


class MetricsCollector:
    """轻量级指标收集器，线程安全。"""

    def __init__(self) -> None:
        # 计数器（累计值）
        self._counters: dict[str, int] = defaultdict(int)
        # 计时器（记录每次耗时，用于计算平均）
        self._timers: dict[str, list[float]] = defaultdict(list)

    def increment(self, metric: str, value: int = 1) -> None:
        """增加计数器。"""
        self._counters[metric] += value

    def record_timing(self, metric: str, duration_ms: float) -> None:
        """记录一次耗时。"""
        self._timers[metric].append(duration_ms)

    @property
    def request_count(self) -> int:
        return self._counters.get("request_total", 0)

    @property
    def agent_success_rate(self) -> float:
        total = self._counters.get("agent_executions", 0)
        if total == 0:
            return 1.0
        return self._counters.get("agent_success", 0) / total

    @property
    def avg_request_latency_ms(self) -> float:
        timings = self._timers.get("request_latency", [])
        if not timings:
            return 0.0
        return sum(timings) / len(timings)

    def get_summary(self) -> dict[str, Any]:
        """获取完整的指标摘要。"""
        avg_timers = {}
        for key, values in self._timers.items():
            avg_timers[f"{key}_avg_ms"] = sum(values) / len(values) if values else 0

        return {
            **dict(self._counters),
            **avg_timers,
            "agent_success_rate": self.agent_success_rate,
            "avg_request_latency_ms": self.avg_request_latency_ms,
        }

    def reset(self) -> None:
        """重置所有指标（测试用）。"""
        self._counters.clear()
        self._timers.clear()


# 全局单例
_metrics_collector = MetricsCollector()


def get_metrics() -> MetricsCollector:
    """获取指标收集器单例。"""
    return _metrics_collector
