"""
Agent 服务层。

处理 Agent 相关的业务逻辑，包括：
- Agent 配置的 CRUD
- Agent 实例的创建与管理
- Agent 运行与流式输出
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.base import BaseAgent
from src.core.exceptions import AgentNotFoundError
from src.db.repository import BaseRepository
from src.llm.factory import LLMFactory
from src.models.domain.agent import AgentConfig


class AgentService:
    """Agent 业务服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = BaseRepository[AgentConfig](AgentConfig, session)
        self._llm_factory = LLMFactory()

    # ---- Agent 配置 CRUD ----

    async def create_agent_config(
        self,
        name: str,
        agent_type: str,
        system_prompt: str,
        model_name: str = "gpt-4o",
        temperature: float = 0.7,
        tools: list[str] | None = None,
        max_tokens: int | None = None,
        tenant_id: str = "default",
    ) -> AgentConfig:
        """创建 Agent 配置。"""
        config = AgentConfig(
            name=name,
            agent_type=agent_type,
            system_prompt=system_prompt,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=json.dumps(tools) if tools else None,
            tenant_id=tenant_id,
        )
        return await self._repo.create(config)

    async def get_agent_config(self, agent_id: str, tenant_id: str) -> AgentConfig:
        """获取 Agent 配置。"""
        config = await self._repo.get_by_id_with_tenant(agent_id, tenant_id)
        if config is None:
            raise AgentNotFoundError(agent_id)
        return config

    async def list_agent_configs(
        self,
        tenant_id: str,
        skip: int = 0,
        limit: int = 100,
    ) -> list[AgentConfig]:
        """获取 Agent 配置列表。"""
        return await self._repo.list_all(tenant_id=tenant_id, skip=skip, limit=limit)

    async def count_agent_configs(self, tenant_id: str) -> int:
        """统计 Agent 配置总数。"""
        return await self._repo.count(tenant_id=tenant_id)

    async def update_agent_config(
        self,
        agent_id: str,
        tenant_id: str,
        **updates: Any,
    ) -> AgentConfig:
        """更新 Agent 配置。"""
        config = await self.get_agent_config(agent_id, tenant_id)
        for field, value in updates.items():
            if value is not None and hasattr(config, field):
                setattr(config, field, value)
        return await self._repo.update(config)

    async def delete_agent_config(self, agent_id: str, tenant_id: str) -> bool:
        """软删除 Agent 配置。"""
        config = await self.get_agent_config(agent_id, tenant_id)
        return await self._repo.soft_delete(config.id)

    # ---- Agent 运行时 ----

    async def create_agent_instance(
        self, agent_config: AgentConfig
    ) -> BaseAgent:
        """根据配置创建可执行的 Agent 实例。"""
        llm = self._llm_factory.create_chat_model(
            model_name=agent_config.model_name,
            temperature=agent_config.temperature,
            max_tokens=agent_config.max_tokens,
        )
        return BaseAgent(
            llm=llm,
            system_prompt=agent_config.system_prompt,
            tenant_id=agent_config.tenant_id,
        )

    async def run_agent(
        self,
        agent_id: str,
        user_input: str,
        tenant_id: str,
        chat_history: list | None = None,
    ) -> dict[str, Any]:
        """运行 Agent 并返回结果。"""
        config = await self.get_agent_config(agent_id, tenant_id)
        agent = await self.create_agent_instance(config)
        return await agent.run(
            user_input=user_input,
            chat_history=chat_history,
            metadata={"agent_id": agent_id, "tenant_id": tenant_id},
        )
