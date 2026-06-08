"""Conversation API 集成测试。"""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    import sys
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    if sys.platform == "win32":
        import asyncio
        await asyncio.sleep(0.1)


@pytest.mark.anyio
class TestConversationCRUD:
    """会话 CRUD 端点测试。"""

    async def test_create_conversation_rejects_unauth(self, client: AsyncClient):
        """未认证用户不能创建会话（返回 422 因 Depends 校验失败）。"""
        resp = await client.post("/api/v1/conversations", json={"title": "test"})
        assert resp.status_code in (401, 403, 422)

    async def test_list_conversations_rejects_unauth(self, client: AsyncClient):
        """未认证用户不能列出会话。"""
        resp = await client.get("/api/v1/conversations")
        assert resp.status_code in (401, 403, 422)

    async def test_get_conversation_rejects_unauth(self, client: AsyncClient):
        """访问会话需要认证。"""
        resp = await client.get("/api/v1/conversations/nonexistent-id")
        assert resp.status_code in (401, 403, 404, 422)

    async def test_send_message_rejects_unauth(self, client: AsyncClient):
        """发送消息需要认证。"""
        resp = await client.post(
            "/api/v1/conversations/test-id/send",
            json={"content": "hello", "mode": "ask"},
        )
        assert resp.status_code in (401, 403, 422)

    async def test_send_message_validates_content(self, client: AsyncClient):
        """发送消息验证 content 必填。"""
        resp = await client.post(
            "/api/v1/conversations/test-id/send",
            json={"mode": "ask"},
        )
        assert resp.status_code == 422  # Pydantic validation error


@pytest.mark.anyio
class TestHealthEndpoint:
    """健康检查端点测试。"""

    async def test_health_returns_ok(self, client: AsyncClient):
        """健康检查返回成功。"""
        resp = await client.get("/api/v1/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert data["data"]["status"] in ("healthy", "degraded")
        assert "checks" in data["data"]

    async def test_health_includes_required_checks(self, client: AsyncClient):
        """健康检查包含所有必需组件。"""
        resp = await client.get("/api/v1/health")
        data = resp.json()["data"]
        checks = data["checks"]
        # 核心检查项
        assert "database" in checks
        assert "redis" in checks or "vector_store" in checks

    async def test_liveness_probe(self, client: AsyncClient):
        """存活探针返回 alive。"""
        resp = await client.get("/api/v1/health/liveness")
        assert resp.status_code == 200
        assert resp.json()["status"] == "alive"

    async def test_readiness_probe(self, client: AsyncClient):
        """就绪探针返回数据库状态。"""
        resp = await client.get("/api/v1/health/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data


@pytest.mark.anyio
class TestMetricsEndpoint:
    """指标端点测试。"""

    async def test_metrics_returns_prometheus_format(self, client: AsyncClient):
        """指标端点返回 Prometheus 格式。"""
        resp = await client.get("/api/v1/metrics")
        assert resp.status_code == 200
        text = resp.text
        # Prometheus 基本格式检查
        assert "app_requests_total" in text or "python_" in text
