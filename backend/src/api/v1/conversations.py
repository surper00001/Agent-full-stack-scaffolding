"""
会话管理 API。

提供多轮对话的创建、查询和管理接口。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant
from src.db.session import get_db_session
from src.models.schemas.request import (
    ChatMessageRequest,
    CreateConversationRequest,
    PaginationParams,
)
from src.models.schemas.response import (
    APIResponse,
    ConversationItem,
    MessageItem,
    PaginatedData,
)
from src.services.conversation_service import ConversationService

router = APIRouter(prefix="/conversations", tags=["会话管理"])


@router.post(
    "", response_model=APIResponse[ConversationItem], summary="创建新会话"
)
async def create_conversation(
    body: CreateConversationRequest,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[ConversationItem]:
    """创建一条新的对话会话。"""
    service = ConversationService(db)
    conv = await service.create_conversation(
        title=body.title,
        agent_type=body.agent_type,
        tenant_id=tenant_id,
    )
    return APIResponse(
        message="会话创建成功", data=ConversationItem.model_validate(conv)
    )


@router.get(
    "", response_model=APIResponse[PaginatedData[ConversationItem]], summary="获取会话列表"
)
async def list_conversations(
    pagination: PaginationParams = Depends(),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[ConversationItem]]:
    """获取当前租户的会话列表。"""
    service = ConversationService(db)
    skip = (pagination.page - 1) * pagination.page_size
    convs = await service.list_conversations(
        tenant_id=tenant_id, skip=skip, limit=pagination.page_size
    )
    total = len(convs)
    return APIResponse(
        data=PaginatedData(
            items=[ConversationItem.model_validate(c) for c in convs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=(total // pagination.page_size) + 1,
        )
    )


@router.get(
    "/{conversation_id}", response_model=APIResponse[ConversationItem], summary="获取会话详情"
)
async def get_conversation(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[ConversationItem]:
    """获取指定会话的详细信息（含消息列表）。"""
    service = ConversationService(db)
    conv = await service.get_conversation(conversation_id, tenant_id)
    return APIResponse(data=ConversationItem.model_validate(conv))


@router.delete(
    "/{conversation_id}", response_model=APIResponse, summary="删除会话"
)
async def delete_conversation(
    conversation_id: str,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """软删除指定会话。"""
    service = ConversationService(db)
    await service.delete_conversation(conversation_id, tenant_id)
    return APIResponse(message="会话已删除")


@router.get(
    "/{conversation_id}/messages",
    response_model=APIResponse[PaginatedData[MessageItem]],
    summary="获取会话消息列表",
)
async def get_messages(
    conversation_id: str,
    pagination: PaginationParams = Depends(),
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[MessageItem]]:
    """获取指定会话的消息历史。"""
    service = ConversationService(db)
    skip = (pagination.page - 1) * pagination.page_size
    msgs = await service.get_messages(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        skip=skip,
        limit=pagination.page_size,
    )
    total = len(msgs)
    return APIResponse(
        data=PaginatedData(
            items=[MessageItem.model_validate(m) for m in msgs],
            total=total,
            page=pagination.page,
            page_size=pagination.page_size,
            pages=(total // pagination.page_size) + 1,
        )
    )


@router.post(
    "/{conversation_id}/send",
    response_model=APIResponse,
    summary="发送消息并获取 Agent 回复",
)
async def send_message(
    conversation_id: str,
    body: ChatMessageRequest,
    tenant_id: str = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """
    向指定会话发送用户消息并获取 Agent 回复。

    这是多轮对话的核心接口：
    1. 保存用户消息
    2. 运行 Agent 获取回复
    3. 保存 Agent 回复
    4. 返回完整响应
    """
    service = ConversationService(db)

    # 1. 保存用户消息
    await service.add_message(
        conversation_id=conversation_id,
        role="user",
        content=body.content,
        tenant_id=tenant_id,
    )

    # 2. 获取历史消息
    messages = await service.get_messages(conversation_id, tenant_id)

    # 3. 运行 Agent（使用默认 Agent 配置）
    #    实际项目可关联 AgentConfig 进行复杂推理
    from src.agents.base import BaseAgent
    from src.llm.factory import get_llm_factory

    llm = get_llm_factory().create_chat_model()
    agent = BaseAgent(llm=llm, tenant_id=tenant_id)
    result = await agent.run(user_input=body.content)

    # 4. 提取 AI 回复并保存
    ai_response = ""
    for msg in reversed(result.get("messages", [])):
        if hasattr(msg, "content") and getattr(msg, "type", "") != "tool":
            ai_response = msg.content
            break

    await service.add_message(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_response,
        token_count=result.get("token_usage", {}).get("total_tokens"),
        tenant_id=tenant_id,
    )

    return APIResponse(
        message="发送成功",
        data={
            "conversation_id": conversation_id,
            "response": ai_response,
            "token_usage": result.get("token_usage", {}),
        },
    )
