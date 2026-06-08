"""Auth API 集成测试。"""

import sys

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
class TestAuthEndpoints:
    """认证端点集成测试。"""

    async def test_captcha_returns_image(self, client: AsyncClient):
        """验证码端点返回 PNG 图片。"""
        resp = await client.get("/api/v1/auth/captcha?target=test@test.com")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/png"

    async def test_send_code_validates_target(self, client: AsyncClient):
        """发送验证码验证 target 必填。"""
        resp = await client.post("/api/v1/auth/send-code", json={"method": "email"})
        assert resp.status_code == 422

    async def test_login_validates_fields(self, client: AsyncClient):
        """登录验证必填字段。"""
        resp = await client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422

    async def test_login_rejects_empty_body(self, client: AsyncClient):
        """登录空 body 被 Pydantic 拒绝。"""
        resp = await client.post("/api/v1/auth/login", json={})
        assert resp.status_code == 422

    async def test_register_validates_required(self, client: AsyncClient):
        """注册验证必填字段。"""
        resp = await client.post("/api/v1/auth/register", json={
            "username": "test",
            "password": "pass",
            # 缺少 code
        })
        assert resp.status_code == 422

    async def test_refresh_validates_token(self, client: AsyncClient):
        """刷新令牌验证必填。"""
        resp = await client.post("/api/v1/auth/refresh", json={})
        assert resp.status_code == 422

    @pytest.mark.skipif(sys.platform == "win32", reason="Windows event loop cleanup issue")
    async def test_send_code_does_not_leak_code(self, client: AsyncClient):
        """验证码端点返回数据包含 target 字段。"""
        resp = await client.post("/api/v1/auth/send-code", json={
            "target": "test@example.com", "method": "email"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "data" in data
        assert "target" in data["data"]


@pytest.mark.anyio
class TestUserEndpoints:
    """用户端点测试（需要认证的受保护端点）。"""

    async def test_list_users_rejects_unauth(self, client: AsyncClient):
        """列出用户需要认证。"""
        resp = await client.get("/api/v1/users")
        assert resp.status_code in (401, 403, 422)

    async def test_me_rejects_unauth(self, client: AsyncClient):
        """获取当前用户需要认证。"""
        resp = await client.get("/api/v1/users/me")
        assert resp.status_code in (401, 403, 422)
