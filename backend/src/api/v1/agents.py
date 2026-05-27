"""
Agent 管理 API。

提供 Agent 配置的 CRUD 和 Agent 执行接口。
（仅管理员可管理 Agent 配置）
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_tenant, get_current_user, require_admin
from src.db.session import get_db_session
from src.models.schemas.request import (
    CreateAgentRequest,
    PaginationParams,
    UpdateAgentRequest,
)
from src.models.schemas.response import AgentConfigItem, APIResponse, PaginatedData
from src.services.agent_service import AgentService

router = APIRouter(prefix="/agents", tags=["Agent 管理"])


@router.post("", response_model=APIResponse[AgentConfigItem], summary="创建 Agent 配置")
async def create_agent(
    body: CreateAgentRequest,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[AgentConfigItem]:
    """创建一个新的 Agent 配置（仅管理员）。"""
    service = AgentService(db)
    config = await service.create_agent_config(
        name=body.name,
        agent_type=body.agent_type,
        system_prompt=body.system_prompt,
        model_name=body.model_name,
        temperature=body.temperature,
        max_tokens=body.max_tokens,
        tools=body.tools,
        tenant_id=tenant_id,
    )
    return APIResponse(message="Agent 创建成功", data=AgentConfigItem.model_validate(config))


@router.get("", response_model=APIResponse[PaginatedData[AgentConfigItem]], summary="获取 Agent 列表")
async def list_agents(
    pagination: PaginationParams = Depends(),
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[AgentConfigItem]]:
    """获取当前租户的 Agent 配置列表（所有认证用户可查看）。"""
    service = AgentService(db)
    skip = (pagination.page - 1) * pagination.page_size
    configs = await service.list_agent_configs(
        tenant_id=tenant_id, skip=skip, limit=pagination.page_size
    )
    total = await service.count_agent_configs(tenant_id=tenant_id)
    return APIResponse(
        data=PaginatedData(
            items=[AgentConfigItem.model_validate(c) for c in configs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=max(1, (total + pagination.page_size - 1) // pagination.page_size),
        )
    )


@router.get("/{agent_id}", response_model=APIResponse[AgentConfigItem], summary="获取 Agent 详情")
async def get_agent(
    agent_id: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[AgentConfigItem]:
    """获取指定 Agent 的配置详情（所有认证用户可查看）。"""
    service = AgentService(db)
    config = await service.get_agent_config(agent_id, tenant_id)
    return APIResponse(data=AgentConfigItem.model_validate(config))


@router.put("/{agent_id}", response_model=APIResponse[AgentConfigItem], summary="更新 Agent 配置")
async def update_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[AgentConfigItem]:
    """更新指定 Agent 的配置（仅管理员）。"""
    service = AgentService(db)
    updates = body.model_dump(exclude_none=True)
    config = await service.update_agent_config(agent_id, tenant_id, **updates)
    return APIResponse(message="Agent 更新成功", data=AgentConfigItem.model_validate(config))


@router.delete("/{agent_id}", response_model=APIResponse, summary="删除 Agent 配置")
async def delete_agent(
    agent_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """软删除指定的 Agent 配置（仅管理员）。"""
    service = AgentService(db)
    await service.delete_agent_config(agent_id, tenant_id)
    return APIResponse(message="Agent 已删除")


@router.post("/{agent_id}/run", response_model=APIResponse, summary="运行 Agent")
async def run_agent(
    agent_id: str,
    user_input: str,
    tenant_id: str = Depends(get_current_tenant),
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """
    运行指定的 Agent 并返回结果。

    简化版本：传入 user_input 查询参数即可获得 Agent 响应。
    完整版本请参考 conversations API（支持多轮对话）。
    """
    service = AgentService(db)
    result = await service.run_agent(
        agent_id=agent_id,
        user_input=user_input,
        tenant_id=tenant_id,
    )
    # 提取最后一条 AI 消息内容
    last_ai_msg = ""
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "content") and getattr(msg, "type", "") != "tool":
            last_ai_msg = msg.content
            break

    return APIResponse(
        message="Agent 执行完成",
        data={
            "response": last_ai_msg,
            "token_usage": result.get("token_usage", {}),
        },
    )
