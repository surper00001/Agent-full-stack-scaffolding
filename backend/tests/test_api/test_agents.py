"""
Agent API 测试。
"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_agent(async_client: AsyncClient) -> None:
    """测试创建 Agent 配置。"""
    payload = {
        "name": "测试助手",
        "agent_type": "chat",
        "system_prompt": "你是一个测试助手",
        "model_name": "gpt-4o",
        "temperature": 0.5,
    }
    response = await async_client.post("/api/v1/agents", json=payload)
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert data["data"]["name"] == "测试助手"
    assert data["data"]["agent_type"] == "chat"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_agent_missing_fields(async_client: AsyncClient) -> None:
    """测试必填字段校验（name 为空应返回 422）。"""
    payload = {
        "name": "",
        "agent_type": "chat",
        "system_prompt": "test",
    }
    response = await async_client.post("/api/v1/agents", json=payload)
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.unit
async def test_list_agents(async_client: AsyncClient) -> None:
    """测试获取 Agent 列表。"""
    response = await async_client.get("/api/v1/agents")
    assert response.status_code == 200

    data = response.json()
    assert data["success"] is True
    assert "items" in data["data"]


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_agent_not_found(async_client: AsyncClient) -> None:
    """测试获取不存在的 Agent 返回 404。"""
    response = await async_client.get(
        "/api/v1/agents/00000000-0000-0000-0000-000000000000"
    )
    assert response.status_code == 404
