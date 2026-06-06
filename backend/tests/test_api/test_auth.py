"""
认证 API 集成测试。

注意：register/login 端点需要 Redis（验证码/限流），
测试环境无 Redis 时这些端点会返回 500/连接错误，
因此仅测试不需要 Redis 的端点（captcha GET 不需要验证码检查）。
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.unit
async def test_register_validation(async_client: AsyncClient) -> None:
    """测试注册请求 schema 校验 — 缺少必填字段 code 返回 422。"""
    payload = {"username": "test", "password": "Test123456!"}
    response = await async_client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.unit
async def test_login_validation(async_client: AsyncClient) -> None:
    """测试登录请求 schema 校验 — 缺少 account 字段返回 422。"""
    payload = {"password": "Test123456!"}
    response = await async_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 422


@pytest.mark.skip(reason="登录端点需要 Redis 限流，测试环境无 Redis")
@pytest.mark.asyncio
@pytest.mark.unit
async def test_login_invalid_credentials(async_client: AsyncClient) -> None:
    """测试不存在的用户登录返回 401。"""
    payload = {"account": "nonexistent_user_xyz", "password": "Whatever123!"}
    response = await async_client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401


@pytest.mark.skip(reason="需要 Redis 连接，测试环境无 Redis 服务")
@pytest.mark.asyncio
@pytest.mark.unit
async def test_captcha_endpoint(async_client: AsyncClient) -> None:
    """测试图形验证码端点可访问（需要 Redis）。"""
    response = await async_client.get("/api/v1/auth/captcha", params={"target": "test@test.com"})
    assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.unit
async def test_refresh_without_token(async_client: AsyncClient) -> None:
    """测试刷新 token 缺少 refresh_token 返回 422。"""
    response = await async_client.post("/api/v1/auth/refresh", json={})
    assert response.status_code == 422
