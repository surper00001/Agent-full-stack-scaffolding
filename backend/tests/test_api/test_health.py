"""
健康检查 API 测试。
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.unit
async def test_health_check(async_client: AsyncClient) -> None:
    """测试完整健康检查接口。"""
    response = await async_client.get("/api/v1/health")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["status"] in ("healthy", "degraded")
    assert data["data"]["version"] == "0.1.0"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_liveness_probe(async_client: AsyncClient) -> None:
    """测试 K8s 存活探针。"""
    response = await async_client.get("/api/v1/health/liveness")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_readiness_probe(async_client: AsyncClient) -> None:
    """测试 K8s 就绪探针。"""
    response = await async_client.get("/api/v1/health/readiness")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
