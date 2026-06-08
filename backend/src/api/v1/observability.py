"""
可观测性 API — 提供系统监控数据给前端大屏。
所有数据来自真实来源：DB 统计、内存追踪器、健康检查。

包含概览、LLM 调用日志、Agent 分析、时序图表数据、模型基准。
"""
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant, get_db_session
from src.services.observability_service import (
    ObservabilityService,
    get_llm_tracker,
)

router = APIRouter(prefix="/admin/observability", tags=["observability"])


@router.get("/overview", summary="可观测性概览")
async def get_observability_overview(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取系统可观测性概览数据（不含 mock）。"""
    service = ObservabilityService(db)
    overview = await service.get_overview()

    return {
        "success": True,
        "data": {
            "stats": {
                "requests_today": overview.requests_today,
                "agent_executions": overview.total_agent_executions,
                "agent_executions_today": overview.agent_executions_today,
                "llm_calls": overview.total_llm_calls,
                "llm_calls_today": overview.llm_calls_today,
                "total_tokens": overview.total_tokens,
                "tokens_today": overview.tokens_today,
                "agent_success_rate": overview.agent_success_rate,
                "llm_avg_latency_ms": overview.llm_avg_latency_ms,
                "total_cost": overview.total_cost,
            },
            "health": await service.get_system_health(),
        },
    }


@router.get("/llm-calls", summary="最近 LLM 调用记录")
async def get_recent_llm_calls(
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """获取最近的 LLM 调用记录（来自内存追踪器）。"""
    tracker = get_llm_tracker()
    records = await tracker.get_recent(limit)
    stats = await tracker.get_stats()

    return {
        "success": True,
        "data": {
            "records": records,
            "stats": stats,
        },
    }


@router.get("/agents", summary="Agent 分析数据")
async def get_agent_analytics(
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取所有 Agent 的分析数据。"""
    service = ObservabilityService(db)
    analytics = await service.get_all_agent_analytics()

    return {
        "success": True,
        "data": {
            "agents": [
                {
                    "name": a.agent_name,
                    "agent_type": a.agent_type,
                    "model_name": a.model_name,
                    "executions": a.total_executions,
                    "success_rate": (
                        round(a.success_count / a.total_executions * 100, 1)
                        if a.total_executions > 0 else 0
                    ),
                    "avg_latency_ms": round(a.avg_latency_ms, 1),
                    "total_tokens": a.total_tokens,
                    "total_cost": a.total_cost,
                    "conversation_count": a.conversation_count,
                }
                for a in analytics
            ],
        },
    }


@router.get("/agents/{agent_id}", summary="单个 Agent 分析")
async def get_single_agent_analytics(
    agent_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取单个 Agent 的详细分析数据。"""
    service = ObservabilityService(db)
    a = await service.get_agent_analytics(agent_id)

    if not a:
        return {"success": False, "message": "Agent 不存在"}

    return {
        "success": True,
        "data": {
            "name": a.agent_name,
            "agent_type": a.agent_type,
            "model_name": a.model_name,
            "executions": a.total_executions,
            "success_count": a.success_count,
            "failure_count": a.failure_count,
            "success_rate": (
                round(a.success_count / a.total_executions * 100, 1)
                if a.total_executions > 0 else 0
            ),
            "avg_latency_ms": round(a.avg_latency_ms, 1),
            "total_tokens": a.total_tokens,
            "total_cost": a.total_cost,
            "conversation_count": a.conversation_count,
        },
    }


# ── 时序图表数据 API ──


@router.get("/time-series/latency", summary="延迟时序数据（图表用）")
async def get_latency_time_series(
    hours: int = Query(24, ge=1, le=168, description="小时数"),
) -> dict[str, Any]:
    """获取按小时聚合的 LLM 延迟数据（avg / p95）。"""
    tracker = get_llm_tracker()
    data = await tracker.get_hourly_latency(hours)
    return {"success": True, "data": data}


@router.get("/time-series/tokens", summary="Token 时序数据（图表用）")
async def get_tokens_time_series(
    days: int = Query(7, ge=1, le=90, description="天数"),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取按天聚合的 Token 消耗时序数据。"""
    service = ObservabilityService(db)
    data = await service.get_daily_tokens(days)
    return {"success": True, "data": data}


@router.get("/time-series/agent-executions", summary="Agent 执行统计（图表用）")
async def get_agent_executions_time_series(
    days: int = Query(7, ge=1, le=90, description="天数"),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """获取按 Agent 聚合的执行统计（成功/失败/超时）。"""
    service = ObservabilityService(db)
    data = await service.get_daily_agent_executions(days)
    return {"success": True, "data": data}


@router.get("/agents/{agent_id}/time-series/executions", summary="单 Agent 每日执行统计")
async def get_agent_daily_executions(
    agent_id: str,
    days: int = Query(7, ge=1, le=90),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = ObservabilityService(db)
    data = await service.get_agent_daily_executions(agent_id, days)
    return {"success": True, "data": data}


@router.get("/agents/{agent_id}/time-series/tokens", summary="单 Agent 每日 Token 统计")
async def get_agent_daily_tokens(
    agent_id: str,
    days: int = Query(7, ge=1, le=90),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = ObservabilityService(db)
    data = await service.get_agent_daily_tokens(agent_id, days)
    return {"success": True, "data": data}


@router.get("/agents/{agent_id}/time-series/cost", summary="单 Agent 每日费用估算")
async def get_agent_daily_cost(
    agent_id: str,
    days: int = Query(7, ge=1, le=90),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = ObservabilityService(db)
    data = await service.get_agent_daily_cost(agent_id, days)
    return {"success": True, "data": data}


@router.get("/agents/{agent_id}/recent-executions", summary="单 Agent 最近执行记录")
async def get_agent_recent_executions(
    agent_id: str,
    limit: int = Query(10, ge=1, le=50),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    service = ObservabilityService(db)
    data = await service.get_agent_recent_executions(agent_id, limit)
    return {"success": True, "data": data}


