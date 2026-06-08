"""
健康检查 API。

提供应用和各依赖组件的深度健康状态检查，
可用作 Kubernetes 的 liveness / readiness 探针。
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import APIRouter
from fastapi.responses import Response
from sqlalchemy import text

from src.models.schemas.response import APIResponse, HealthResponse

router = APIRouter(tags=["健康检查"])

# 记录应用启动时间
_start_time = time.time()


# ── 独立检查器 ──

async def _check_database() -> dict[str, Any]:
    """检查 PostgreSQL 连通性和版本。"""
    try:
        from src.db.session import AsyncSessionLocal

        start = time.perf_counter()
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            result.fetchone()
        latency = round((time.perf_counter() - start) * 1000, 2)

        # 获取数据库版本 — 兼容 PostgreSQL 和 SQLite
        async with AsyncSessionLocal() as session:
            try:
                ver_result = await session.execute(text("SELECT version()"))
                version = str(ver_result.scalar_one())[:60]
            except Exception:
                ver_result = await session.execute(text("SELECT sqlite_version()"))
                version = f"SQLite {ver_result.scalar_one()}"

        return {"status": "healthy", "latency_ms": latency, "version": version}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_redis() -> dict[str, Any]:
    """检查 Redis 连通性和内存。"""
    try:
        from src.core.redis import get_redis_client

        redis = get_redis_client()
        if redis is None:
            return {"status": "disabled", "message": "Redis 未配置或不可用"}

        start = time.perf_counter()
        pong = await redis.ping()
        latency = round((time.perf_counter() - start) * 1000, 2)

        info = await redis.info("memory")
        return {
            "status": "healthy" if pong else "unhealthy",
            "latency_ms": latency,
            "used_memory_human": info.get("used_memory_human", "N/A"),
            "connected_clients": info.get("connected_clients", 0),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


def _check_disk() -> dict[str, Any]:
    """检查知识库数据目录的磁盘空间。兼容 Windows（无 statvfs）。"""
    try:
        from src.core.config import get_settings

        data_dir = get_settings().kb_storage_dir
        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)

        try:
            usage = os.statvfs(data_dir)
            total_gb = round(usage.f_frsize * usage.f_blocks / (1024**3), 1)
            free_gb = round(usage.f_frsize * usage.f_bavail / (1024**3), 1)
        except AttributeError:
            # Windows 不支持 statvfs，使用 shutil 回退
            import shutil as _shutil
            disk = _shutil.disk_usage(data_dir)
            total_gb = round(disk.total / (1024**3), 1)
            free_gb = round(disk.free / (1024**3), 1)

        used_pct = round((1 - free_gb / total_gb) * 100, 1) if total_gb > 0 else 0

        return {
            "status": "healthy" if free_gb > 1 else "warning",
            "total_gb": total_gb,
            "free_gb": free_gb,
            "used_percent": used_pct,
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


async def _check_llm() -> dict[str, Any]:
    """检查 LLM 提供商连通性（轻量测试调用）。"""
    try:
        from src.llm.factory import get_llm_factory
        from langchain_core.messages import HumanMessage

        factory = get_llm_factory()
        llm = factory.create_chat_model()
        if llm is None:
            return {"status": "disabled", "message": "LLM 未配置"}

        import time as _time
        start = _time.perf_counter()
        resp = await llm.ainvoke([HumanMessage(content="ping")], max_tokens=1)
        latency = round((_time.perf_counter() - start) * 1000, 2)

        return {
            "status": "healthy",
            "latency_ms": latency,
            "model": getattr(llm, "model_name", "unknown"),
        }
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}


# ── 端点 ──

@router.get("/health", response_model=APIResponse[HealthResponse], summary="深度健康检查")
async def health_check() -> APIResponse[HealthResponse]:
    """全面健康检查：DB + Redis + 向量存储 + 磁盘空间。"""
    checks: dict[str, str] = {}

    # DB
    db = await _check_database()
    checks["database"] = db.get("status", "unknown")
    if "latency_ms" in db:
        checks["database"] = f"{checks['database']} ({db['latency_ms']}ms)"

    # Redis
    rds = await _check_redis()
    checks["redis"] = rds.get("status", "unknown")

    # 向量存储
    try:
        from src.vectorstore.base import create_vector_store

        store = create_vector_store()
        vdb = await store.health_check()
        checks["vector_store"] = "healthy" if vdb else "unhealthy"
    except Exception as e:
        checks["vector_store"] = f"error: {e}"

    # 磁盘
    disk = _check_disk()
    checks["disk"] = disk.get("status", "unknown")

    # LLM 提供商
    llm = await _check_llm()
    checks["llm"] = llm.get("status", "unknown")

    # 汇总
    unhealthy = [k for k, v in checks.items() if v.startswith(("unhealthy", "error"))]
    status = "healthy" if not unhealthy else "degraded"

    return APIResponse(
        data=HealthResponse(
            status=status,
            version="0.1.0",
            uptime=time.time() - _start_time,
            checks=checks,
        )
    )


@router.get("/health/liveness", summary="存活探针（仅检查进程存活）")
async def liveness() -> dict[str, str]:
    """Kubernetes liveness probe，仅验证进程未挂。"""
    return {"status": "alive"}


@router.get("/metrics", summary="Prometheus 指标导出")
async def metrics() -> Response:
    """导出 Prometheus 格式的运行时指标（供 Prometheus/Grafana 抓取）。"""
    from src.monitoring.metrics import get_prometheus_metrics

    return Response(content=get_prometheus_metrics(), media_type="text/plain; charset=utf-8")


@router.get("/health/readiness", summary="就绪探针（检查 DB + Redis）")
async def readiness() -> dict[str, Any]:
    """Kubernetes readiness probe，验证 DB 和 Redis 可用。"""
    db = await _check_database()
    redis = await _check_redis()

    db_ok = db.get("status") == "healthy"
    # Redis 非关键依赖，连接不上也标记为就绪（降级运行）
    redis_ok = redis.get("status") in ("healthy", "disabled", "unhealthy")
    all_ok = db_ok

    return {
        "status": "ready" if all_ok else "not_ready",
        "checks": {"database": db_ok, "redis": redis_ok},
    }
