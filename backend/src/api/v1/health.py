"""
健康检查 API。

提供应用和各依赖组件的健康状态检查，
可用于 Kubernetes 的 liveness 和 readiness 探针。
"""

import time

from fastapi import APIRouter

from src.models.schemas.response import APIResponse, HealthResponse

router = APIRouter(tags=["健康检查"])

# 记录应用启动时间
_start_time = time.time()


@router.get("/health", response_model=APIResponse[HealthResponse], summary="健康检查")
async def health_check() -> APIResponse[HealthResponse]:
    """
    全面健康检查。

    检查数据库、Redis、向量数据库等组件的连接状态。
    Kubernetes 可用此端点做 liveness probe。
    """
    checks: dict[str, str] = {}

    # 检查向量数据库
    try:
        from src.vectorstore.chroma_store import ChromaVectorStore

        store = ChromaVectorStore()
        vdb = await store.health_check()
        checks["vector_store"] = "healthy" if vdb else "unhealthy"
    except Exception as e:
        checks["vector_store"] = f"error: {e}"

    # 汇总状态
    all_healthy = all(v == "healthy" for v in checks.values())
    status = "healthy" if all_healthy else "degraded"

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


@router.get("/health/readiness", summary="就绪探针（检查依赖组件）")
async def readiness() -> dict[str, str]:
    """Kubernetes readiness probe，验证应用已就绪接收流量。"""
    return {"status": "ready"}
