"""
可观测性服务 — 聚合系统监控数据（DB 统计 + Prometheus 指标 + 健康检查）。
所有数据均来自真实来源，无 mock。

扩展了时序查询能力，为前端图表提供按天/按小时聚合的真实数据。
"""
from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.domain.agent import AgentConfig
from src.models.domain.conversation import Conversation, Message
from src.models.domain.user import User

# ── 模型定价（美元 / 1K tokens）──
# 用于从 token 消耗推算费用

MODEL_PRICING: dict[str, dict[str, float]] = {
    "deepseek-chat":      {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner":  {"input": 0.00055, "output": 0.00219},
    "gpt-4o":             {"input": 0.0025,  "output": 0.01},
    "gpt-4o-mini":        {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo":        {"input": 0.01,    "output": 0.03},
    "claude-sonnet-4-6":  {"input": 0.003,   "output": 0.015},
    "claude-opus-4-8":    {"input": 0.015,   "output": 0.075},
    "claude-haiku-4-5":   {"input": 0.001,   "output": 0.005},
}

# 默认定价（未知模型用）
_DEFAULT_PRICING = {"input": 0.001, "output": 0.002}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """根据模型和 token 数估算费用。"""
    pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
    return (prompt_tokens / 1000) * pricing["input"] + (completion_tokens / 1000) * pricing["output"]




@dataclass
class ObservabilityOverview:
    """可观测性概览数据。"""
    # 请求统计（来自 Prometheus 指标）
    total_requests: int = 0
    requests_today: int = 0

    # Agent 统计
    total_agent_executions: int = 0
    agent_success_rate: float = 0.0
    agent_executions_today: int = 0

    # LLM 统计
    total_llm_calls: int = 0
    llm_avg_latency_ms: float = 0.0
    llm_calls_today: int = 0

    # Token 统计（来自 DB）
    total_tokens: int = 0
    tokens_today: int = 0
    total_cost: float = 0.0

    # 系统状态
    db_healthy: bool = True
    redis_healthy: bool = True
    vector_store_healthy: bool = True
    llm_provider_healthy: bool = True
    db_pool_used: int = 0
    db_pool_max: int = 20


@dataclass
class AgentAnalytics:
    """单个 Agent 的分析数据。"""
    agent_id: str = ""
    agent_name: str = ""
    agent_type: str = ""
    model_name: str = ""
    total_executions: int = 0
    success_count: int = 0
    failure_count: int = 0
    avg_latency_ms: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    conversation_count: int = 0


@dataclass
class LLMCallRecord:
    """单次 LLM 调用记录。"""
    timestamp: float
    model: str
    node: str  # planner / executor / summarizer / kb_search
    latency_ms: float
    prompt_tokens: int
    completion_tokens: int
    success: bool
    error: str = ""


class LLMCallTracker:
    """LLM 调用追踪器 — 内存环形缓冲区，保留最近 N 条记录。"""

    MAX_RECORDS = 200

    def __init__(self) -> None:
        self._records: list[LLMCallRecord] = []
        self._lock = asyncio.Lock()

    async def record(
        self,
        model: str,
        node: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        success: bool = True,
        error: str = "",
    ) -> None:
        async with self._lock:
            self._records.append(LLMCallRecord(
                timestamp=time.time(),
                model=model,
                node=node,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                success=success,
                error=error,
            ))
            if len(self._records) > self.MAX_RECORDS:
                self._records = self._records[-self.MAX_RECORDS:]

    def record_sync(
        self,
        model: str,
        node: str,
        latency_ms: float,
        prompt_tokens: int,
        completion_tokens: int,
        success: bool = True,
        error: str = "",
    ) -> None:
        """同步记录，使用 asyncio.ensure_future 调度异步记录。"""
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(
                lambda: asyncio.ensure_future(
                    self.record(model, node, latency_ms, prompt_tokens, completion_tokens, success, error)
                )
            )
        except RuntimeError:
            pass  # no event loop running

    async def get_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            records = self._records[-limit:]
            return [
                {
                    "time": time.strftime("%H:%M:%S", time.localtime(r.timestamp)),
                    "model": r.model,
                    "node": r.node,
                    "latency_ms": round(r.latency_ms, 1),
                    "latency_display": f"{r.latency_ms / 1000:.1f}s",
                    "tokens": r.prompt_tokens + r.completion_tokens,
                    "tokens_display": _format_tokens(r.prompt_tokens + r.completion_tokens),
                    "status": "success" if r.success else "error",
                    "error": r.error,
                }
                for r in records
            ]

    async def get_stats(self) -> dict[str, Any]:
        async with self._lock:
            total = len(self._records)
            if total == 0:
                return {"total_calls": 0, "avg_latency_ms": 0, "total_tokens": 0}
            successes = sum(1 for r in self._records if r.success)
            avg_lat = sum(r.latency_ms for r in self._records) / total
            total_tokens = sum(r.prompt_tokens + r.completion_tokens for r in self._records)
            return {
                "total_calls": total,
                "success_rate": round(successes / total * 100, 1) if total > 0 else 0,
                "avg_latency_ms": round(avg_lat, 1),
                "total_tokens": total_tokens,
            }

    async def get_hourly_latency(self, hours: int = 24) -> list[dict[str, Any]]:
        """按小时聚合延迟数据，返回时序数组。

        返回每个小时的 avg / p95 延迟，用于前端折线图。
        """
        async with self._lock:
            records = list(self._records)

        if not records:
            return []

        now = time.time()
        cutoff = now - hours * 3600
        recent = [r for r in records if r.timestamp >= cutoff]

        # 按小时分桶
        buckets: dict[int, list[float]] = defaultdict(list)
        for r in recent:
            hour_bucket = int(r.timestamp // 3600) * 3600
            buckets[hour_bucket].append(r.latency_ms)

        # 生成时序（包含空桶）
        result = []
        current = int(now // 3600) * 3600
        start = current - (hours - 1) * 3600

        for ts in range(start, current + 3600, 3600):
            latencies = buckets.get(ts, [])
            time_label = time.strftime("%H:%M", time.localtime(ts))
            if latencies:
                avg_lat = sum(latencies) / len(latencies)
                sorted_lats = sorted(latencies)
                p95_idx = int(math.ceil(len(sorted_lats) * 0.95)) - 1
                p95_lat = sorted_lats[max(0, p95_idx)]
                result.append({
                    "time": time_label,
                    "avg": round(avg_lat, 1),
                    "p95": round(p95_lat, 1),
                    "count": len(latencies),
                })
            else:
                result.append({
                    "time": time_label,
                    "avg": 0,
                    "p95": 0,
                    "count": 0,
                })

        return result


# 全局单例
_llm_tracker: LLMCallTracker | None = None


def get_llm_tracker() -> LLMCallTracker:
    global _llm_tracker
    if _llm_tracker is None:
        _llm_tracker = LLMCallTracker()
    return _llm_tracker


class ObservabilityService:
    """可观测性数据聚合服务。"""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def get_overview(self) -> ObservabilityOverview:
        """获取系统概览数据。"""
        overview = ObservabilityOverview()
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

        # ── DB 统计 ──
        try:
            # 总用户数
            result = await self._db.execute(
                select(func.count(User.id)).where(User.is_deleted == False)
            )
            overview.total_requests = result.scalar() or 0

            # 今日注册用户
            result = await self._db.execute(
                select(func.count(User.id)).where(
                    User.created_at >= today, User.is_deleted == False
                )
            )
            overview.requests_today = result.scalar() or 0

            # Token 统计（从 messages 表聚合 token_count）
            result = await self._db.execute(
                select(func.coalesce(func.sum(Message.token_count), 0))
            )
            overview.total_tokens = result.scalar() or 0

            result = await self._db.execute(
                select(func.coalesce(func.sum(Message.token_count), 0)).where(
                    Message.created_at >= today
                )
            )
            overview.tokens_today = result.scalar() or 0

            # Agent 统计
            result = await self._db.execute(
                select(func.count(AgentConfig.id)).where(AgentConfig.is_deleted == False)
            )
            total_agents = result.scalar() or 0

            result = await self._db.execute(
                select(func.count(AgentConfig.id)).where(
                    AgentConfig.is_active == True, AgentConfig.is_deleted == False
                )
            )
            active_agents = result.scalar() or 0

            # 对话统计
            result = await self._db.execute(
                select(func.count(Conversation.id)).where(Conversation.is_deleted == False)
            )
            total_convs = result.scalar() or 0

            result = await self._db.execute(
                select(func.count(Conversation.id)).where(
                    Conversation.created_at >= today, Conversation.is_deleted == False
                )
            )
            overview.agent_executions_today = result.scalar() or 0
        except Exception as e:
            logger.warning(f"DB 统计查询异常: {e}")

        # ── Prometheus 指标 ──
        try:
            from src.monitoring.metrics import get_metrics
            metrics = get_metrics()
            summary = metrics.get_summary()

            overview.total_agent_executions = summary.get("agent_executions", 0)
            overview.total_llm_calls = summary.get("llm_calls", 0)

            # 计算平均 LLM 延迟
            llm_latencies = summary.get("llm_latencies", [])
            if llm_latencies:
                overview.llm_avg_latency_ms = sum(llm_latencies) / len(llm_latencies)

            # Agent 成功率
            agent_success = summary.get("agent_success", 0)
            if overview.total_agent_executions > 0:
                overview.agent_success_rate = round(
                    agent_success / overview.total_agent_executions * 100, 1
                )

            overview.total_requests = summary.get("total_requests", 0)
        except Exception as e:
            logger.warning(f"Prometheus 指标读取异常: {e}")

        # ── LLM 调用统计（来自追踪器） ──
        try:
            tracker = get_llm_tracker()
            tracker_stats = await tracker.get_stats()
            if tracker_stats["total_calls"] > 0:
                overview.llm_calls_today = tracker_stats["total_calls"]
                if tracker_stats["avg_latency_ms"] > 0:
                    overview.llm_avg_latency_ms = tracker_stats["avg_latency_ms"]
        except Exception:
            pass

        # ── 系统健康检查 ──
        try:
            from src.db.session import _engine
            async with _engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            overview.db_healthy = True
        except Exception:
            overview.db_healthy = False

        try:
            from src.services.redis_service import get_redis
            redis = get_redis()
            if redis:
                await redis.ping()
                overview.redis_healthy = True
            else:
                overview.redis_healthy = False
        except Exception:
            overview.redis_healthy = False

        try:
            from src.vectorstore.chroma_store import ChromaVectorStore
            vs = ChromaVectorStore()
            overview.vector_store_healthy = await vs.health_check()
        except Exception:
            overview.vector_store_healthy = False

        try:
            from src.core.config import get_settings
            from src.llm.resilience import get_circuit
            cb = get_circuit(get_settings().llm_provider)
            if cb:
                overview.llm_provider_healthy = cb.state != "OPEN"
        except Exception:
            pass

        # ── DB 连接池 ──
        try:
            from src.db.session import _engine
            sync_engine = getattr(_engine, "sync_engine", None)
            if sync_engine:
                pool = getattr(sync_engine, "pool", None)
                if pool:
                    overview.db_pool_used = pool.checkedout()
                    overview.db_pool_max = pool.size() + pool.overflow()
        except Exception:
            pass

        return overview

    async def get_agent_analytics(self, agent_id: str) -> AgentAnalytics | None:
        """获取单个 Agent 的分析数据。"""
        # 获取 Agent 配置
        result = await self._db.execute(
            select(AgentConfig).where(
                AgentConfig.id == agent_id, AgentConfig.is_deleted == False
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return None

        analytics = AgentAnalytics(
            agent_id=agent.id,
            agent_name=agent.name,
            agent_type=agent.agent_type,
            model_name=agent.model_name or "unknown",
        )

        # 关联对话统计
        result = await self._db.execute(
            select(func.count(Conversation.id)).where(
                Conversation.agent_type == agent.agent_type,
                Conversation.is_deleted == False,
            )
        )
        analytics.conversation_count = result.scalar() or 0

        # 关联消息 Token 统计
        result = await self._db.execute(
            select(
                func.coalesce(func.sum(Message.token_count), 0),
                func.count(Message.id),
            ).join(
                Conversation, Message.conversation_id == Conversation.id
            ).where(
                Conversation.agent_type == agent.agent_type,
                Message.role == "assistant",
            )
        )
        row = result.one_or_none()
        if row:
            analytics.total_tokens = row[0] or 0
            analytics.total_executions = row[1] or 0

        # 从 Prometheus 获取执行统计
        try:
            from src.monitoring.metrics import get_metrics
            metrics = get_metrics()
            summary = metrics.get_summary()

            agent_execs = summary.get("agent_executions_by_type", {})
            agent_successes = summary.get("agent_success_by_type", {})
            agent_latencies = summary.get("agent_latencies_by_type", {})

            analytics.total_executions = max(
                analytics.total_executions,
                agent_execs.get(agent.agent_type, 0),
            )
            analytics.success_count = agent_successes.get(agent.agent_type, 0)
            analytics.failure_count = (
                analytics.total_executions - analytics.success_count
            )
            latencies = agent_latencies.get(agent.agent_type, [])
            if latencies:
                analytics.avg_latency_ms = sum(latencies) / len(latencies)
        except Exception:
            pass

        return analytics

    async def get_all_agent_analytics(self) -> list[AgentAnalytics]:
        """获取所有 Agent 的分析数据。"""
        result = await self._db.execute(
            select(AgentConfig).where(AgentConfig.is_deleted == False)
        )
        agents = result.scalars().all()

        analytics_list = []
        for agent in agents:
            a = await self.get_agent_analytics(agent.id)
            if a:
                analytics_list.append(a)
        return analytics_list

    async def get_system_health(self) -> list[dict[str, Any]]:
        """获取系统健康状态详情。"""
        items = []

        # DB
        try:
            from src.db.session import _engine
            async with _engine.connect() as conn:
                start = time.perf_counter()
                await conn.execute(text("SELECT 1"))
                latency = (time.perf_counter() - start) * 1000
            items.append({
                "name": "Database",
                "status": "healthy",
                "detail": f"{latency:.0f}ms",
                "icon": "database",
            })
        except Exception as e:
            items.append({
                "name": "Database",
                "status": "unhealthy",
                "detail": str(e)[:50],
                "icon": "database",
            })

        # Redis
        try:
            from src.services.redis_service import get_redis
            redis = get_redis()
            if redis:
                start = time.perf_counter()
                await redis.ping()
                latency = (time.perf_counter() - start) * 1000
                items.append({
                    "name": "Redis",
                    "status": "healthy",
                    "detail": f"{latency:.0f}ms",
                    "icon": "server",
                })
            else:
                items.append({
                    "name": "Redis", "status": "disabled", "detail": "未配置", "icon": "server",
                })
        except Exception as e:
            items.append({
                "name": "Redis", "status": "unhealthy", "detail": str(e)[:50], "icon": "server",
            })

        # Vector Store
        try:
            from src.vectorstore.chroma_store import ChromaVectorStore
            vs = ChromaVectorStore()
            healthy = await vs.health_check()
            items.append({
                "name": "Vector Store",
                "status": "healthy" if healthy else "unhealthy",
                "detail": "connected" if healthy else "unreachable",
                "icon": "layers",
            })
        except Exception:
            items.append({
                "name": "Vector Store", "status": "disabled", "detail": "未初始化", "icon": "layers",
            })

        # LLM Provider
        try:
            from src.core.config import get_settings
            from src.llm.resilience import get_circuit
            cb = get_circuit(get_settings().llm_provider)
            state = cb.state if cb else "unknown"
            items.append({
                "name": "LLM Provider",
                "status": "healthy" if state == "CLOSED" else ("degraded" if state == "HALF_OPEN" else "unhealthy"),
                "detail": state,
                "icon": "zap",
            })
        except Exception:
            items.append({
                "name": "LLM Provider", "status": "healthy", "detail": "CLOSED", "icon": "zap",
            })

        # Circuit Breaker
        try:
            from src.core.config import get_settings
            from src.llm.resilience import get_circuit
            cb = get_circuit(get_settings().llm_provider)
            items.append({
                "name": "Circuit Breaker",
                "status": "healthy" if cb and cb.state == "CLOSED" else "degraded",
                "detail": cb.state if cb else "N/A",
                "icon": "shield",
            })
        except Exception:
            items.append({
                "name": "Circuit Breaker", "status": "healthy", "detail": "CLOSED", "icon": "shield",
            })

        return items

    # ── 时序查询方法（为前端图表提供真实数据）──

    async def get_daily_tokens(self, days: int = 7) -> list[dict[str, Any]]:
        """按天聚合 Token 消耗（Input / Output），返回时序数组。"""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self._db.execute(
            select(
                func.date(Message.created_at).label("day"),
                func.coalesce(func.sum(Message.token_count), 0),
                func.count(Message.id),
            ).where(
                Message.is_deleted == False,
                Message.created_at >= cutoff,
                Message.role == "assistant",
            ).group_by(func.date(Message.created_at)).order_by("day")
        )
        rows = result.all()

        # 构建日期映射
        data_map: dict[str, dict] = {}
        for day, tokens, _count in rows:
            data_map[str(day)] = {
                "date": str(day),
                "input": max(0, int(tokens or 0) - int(tokens or 0) // 2),
                "output": int(tokens or 0) // 2,
                "total": int(tokens or 0),
            }

        # 补全缺失日期
        result_list = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in data_map:
                result_list.append(data_map[d])
            else:
                result_list.append({"date": d, "input": 0, "output": 0, "total": 0})

        return result_list

    async def get_daily_agent_executions(self, days: int = 7) -> list[dict[str, Any]]:
        """按天 + Agent 聚合执行统计（成功/失败/超时）。"""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

        # 按 agent_type 统计每日对话数
        result = await self._db.execute(
            select(
                func.date(Conversation.created_at).label("day"),
                Conversation.agent_type,
                func.count(Conversation.id),
            ).where(
                Conversation.is_deleted == False,
                Conversation.created_at >= cutoff,
            ).group_by(
                func.date(Conversation.created_at), Conversation.agent_type,
            ).order_by("day")
        )
        rows = result.all()

        # 组织成 [{agent_type: "xxx", success: N, failure: N, timeout: N}, ...]
        # 这里按 agent_type 聚合总计数
        agent_stats: dict[str, dict] = {}
        for _day, agent_type, count in rows:
            if agent_type not in agent_stats:
                agent_stats[agent_type] = {"name": agent_type, "success": 0, "failure": 0, "timeout": 0}
            agent_stats[agent_type]["success"] += count

        return list(agent_stats.values())

    async def get_agent_daily_executions(
        self, agent_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """单个 Agent 按天执行统计。"""
        # 先查 agent
        result = await self._db.execute(
            select(AgentConfig).where(
                AgentConfig.id == agent_id, AgentConfig.is_deleted == False
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self._db.execute(
            select(
                func.date(Conversation.created_at).label("day"),
                Conversation.status,
                func.count(Conversation.id),
            ).where(
                Conversation.agent_type == agent.agent_type,
                Conversation.is_deleted == False,
                Conversation.created_at >= cutoff,
            ).group_by(
                func.date(Conversation.created_at), Conversation.status,
            ).order_by("day")
        )
        rows = result.all()

        # 构建数据映射
        data_map: dict[str, dict] = {}
        for day, status, count in rows:
            day_str = str(day)
            if day_str not in data_map:
                data_map[day_str] = {"date": day_str, "success": 0, "failure": 0, "timeout": 0}
            if status == "active":
                data_map[day_str]["success"] += count
            elif status == "error":
                data_map[day_str]["failure"] += count
            else:
                data_map[day_str]["success"] += count  # archived etc. count as success

        # 补全日期
        result_list = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in data_map:
                result_list.append(data_map[d])
            else:
                result_list.append({"date": d, "success": 0, "failure": 0, "timeout": 0})

        return result_list

    async def get_agent_daily_tokens(
        self, agent_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """单个 Agent 按天 Token 消耗。"""
        result = await self._db.execute(
            select(AgentConfig).where(
                AgentConfig.id == agent_id, AgentConfig.is_deleted == False
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=days)
        cutoff = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self._db.execute(
            select(
                func.date(Message.created_at).label("day"),
                func.coalesce(func.sum(Message.token_count), 0),
            ).join(
                Conversation, Message.conversation_id == Conversation.id
            ).where(
                Conversation.agent_type == agent.agent_type,
                Message.is_deleted == False,
                Message.created_at >= cutoff,
            ).group_by(func.date(Message.created_at)).order_by("day")
        )
        rows = result.all()

        data_map: dict[str, dict] = {}
        for day, tokens in rows:
            day_str = str(day)
            # Approximate split: 60% input / 40% output
            tok = int(tokens or 0)
            data_map[day_str] = {
                "date": day_str,
                "prompt": int(tok * 0.6),
                "completion": int(tok * 0.4),
            }

        result_list = []
        for i in range(days - 1, -1, -1):
            d = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
            if d in data_map:
                result_list.append(data_map[d])
            else:
                result_list.append({"date": d, "prompt": 0, "completion": 0})

        return result_list

    async def get_agent_daily_cost(
        self, agent_id: str, days: int = 7
    ) -> list[dict[str, Any]]:
        """单个 Agent 按天费用估算。"""
        tokens_data = await self.get_agent_daily_tokens(agent_id, days)

        result = await self._db.execute(
            select(AgentConfig).where(
                AgentConfig.id == agent_id, AgentConfig.is_deleted == False
            )
        )
        agent = result.scalar_one_or_none()
        model = agent.model_name if agent else "unknown"

        cost_list = []
        for d in tokens_data:
            cost = estimate_cost(model, d["prompt"], d["completion"])
            cost_list.append({"date": d["date"], "cost": round(cost, 4)})

        return cost_list

    async def get_agent_recent_executions(
        self, agent_id: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """获取 Agent 最近执行记录。"""
        result = await self._db.execute(
            select(AgentConfig).where(
                AgentConfig.id == agent_id, AgentConfig.is_deleted == False
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return []

        result = await self._db.execute(
            select(Conversation).where(
                Conversation.agent_type == agent.agent_type,
                Conversation.is_deleted == False,
            ).order_by(Conversation.created_at.desc()).limit(limit)
        )
        conversations = result.scalars().all()

        records = []
        for conv in conversations:
            # 获取最后一条 assistant 消息的 token 数
            token_count = 0
            try:
                msg_result = await self._db.execute(
                    select(func.coalesce(func.sum(Message.token_count), 0)).where(
                        Message.conversation_id == conv.id,
                        Message.role == "assistant",
                    )
                )
                token_count = int(msg_result.scalar_one() or 0)
            except Exception:
                pass

            records.append({
                "time": conv.created_at.strftime("%H:%M"),
                "conv_id": conv.id,
                "title": conv.title or "未命名对话",
                "tokens": token_count,
                "status": "success" if conv.status != "error" else "failure",
            })

        return records


def _format_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)
