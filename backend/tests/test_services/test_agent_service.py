"""
Agent 服务层单元测试。

使用内存 SQLite 数据库进行隔离测试。
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AgentNotFoundError
from src.services.agent_service import AgentService


@pytest.mark.asyncio
@pytest.mark.unit
async def test_create_agent_config(db_session: AsyncSession) -> None:
    """测试创建 Agent 配置。"""
    service = AgentService(db_session)
    config = await service.create_agent_config(
        name="测试 Agent",
        agent_type="qa",
        system_prompt="你是一个测试 QA 助手",
        tenant_id="test_tenant",
    )
    assert config.id is not None
    assert config.name == "测试 Agent"
    assert config.agent_type == "qa"
    assert config.tenant_id == "test_tenant"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_agent_config(db_session: AsyncSession) -> None:
    """测试获取 Agent 配置。"""
    service = AgentService(db_session)
    created = await service.create_agent_config(
        name="可查询 Agent",
        agent_type="default",
        system_prompt="test",
        tenant_id="test_tenant",
    )
    fetched = await service.get_agent_config(created.id, "test_tenant")
    assert fetched.id == created.id
    assert fetched.name == "可查询 Agent"


@pytest.mark.asyncio
@pytest.mark.unit
async def test_get_agent_not_found(db_session: AsyncSession) -> None:
    """测试获取不存在的 Agent 抛出异常。"""
    service = AgentService(db_session)
    with pytest.raises(AgentNotFoundError):
        await service.get_agent_config(
            "00000000-0000-0000-0000-000000000000", "test_tenant"
        )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_list_agent_configs(db_session: AsyncSession) -> None:
    """测试 Agent 列表查询。"""
    service = AgentService(db_session)
    await service.create_agent_config(
        name="Agent A",
        agent_type="type_a",
        system_prompt="prompt a",
        tenant_id="tenant_1",
    )
    await service.create_agent_config(
        name="Agent B",
        agent_type="type_b",
        system_prompt="prompt b",
        tenant_id="tenant_1",
    )

    configs = await service.list_agent_configs("tenant_1")
    assert len(configs) >= 2


@pytest.mark.asyncio
@pytest.mark.unit
async def test_soft_delete_agent(db_session: AsyncSession) -> None:
    """测试软删除 Agent 配置。"""
    service = AgentService(db_session)
    created = await service.create_agent_config(
        name="待删除 Agent",
        agent_type="default",
        system_prompt="test",
        tenant_id="test_tenant",
    )

    result = await service.delete_agent_config(created.id, "test_tenant")
    assert result is True

    # 删除后不应再查到
    with pytest.raises(AgentNotFoundError):
        await service.get_agent_config(created.id, "test_tenant")
