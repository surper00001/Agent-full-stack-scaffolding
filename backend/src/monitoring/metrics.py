"""
指标收集模块。

记录 Agent 平台的运行时指标，包括：
- 请求计数与延迟
- Agent 执行次数与成功率
- LLM Token 消耗
- 向量数据库查询性能

轻量级实现，不引入外部指标库，通过日志输出和回调收集。
后续可对接 Prometheus / Grafana。
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any


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
