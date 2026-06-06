"""
用户管理 API 集成测试（管理员权限）。
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.unit
async def test_list_users(async_client: AsyncClient) -> None:
    """测试管理员获取用户列表。"""
    response = await async_client.get("/api/v1/users")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert "items" in data["data"]
    assert "total" in data["data"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_list_users_pagination(async_client: AsyncClient) -> None:
    """测试用户列表分页参数。"""
    response = await async_client.get("/api/v1/users", params={"page": 1, "page_size": 5})
    assert response.status_code == 200

    data = response.json()
    assert data["data"]["page"] == 1
    assert data["data"]["page_size"] == 5


@pytest.mark.asyncio
@pytest.mark.unit
async def test_list_users_search(async_client: AsyncClient) -> None:
    """测试用户搜索（搜不存在的用户返回空列表）。"""
    response = await async_client.get("/api/v1/users", params={"search": "zzz_no_such_user_xyz"})
    assert response.status_code == 200

    data = response.json()
    assert data["data"]["total"] == 0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_user_not_found(async_client: AsyncClient) -> None:
    """测试获取不存在的用户返回 404。"""
    response = await async_client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000099999"
    )
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.unit
async def test_users_endpoint_protected() -> None:
    """测试未认证访问用户列表被拒绝。"""
    from httpx import ASGITransport, AsyncClient
    from src.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/users")
        # FastAPI dependency 拒绝未认证请求：422（validation）或 401/403
        assert response.status_code in (401, 403, 422)
