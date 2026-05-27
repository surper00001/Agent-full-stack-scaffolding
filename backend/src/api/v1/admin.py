"""管理员仪表盘统计 API。"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_admin
from src.db.session import get_db_session
from src.models.domain.conversation import Conversation, Message
from src.models.domain.user import User
from src.models.schemas.response import APIResponse


class AdminStatsResponse(BaseModel):
    """管理员仪表盘统计数据。"""

    total_users: int = 0
    total_conversations: int = 0
    total_messages: int = 0
    total_tokens: int = 0
    active_users_today: int = 0
    tokens_today: int = 0


router = APIRouter(prefix="/admin", tags=["管理统计"])


@router.get("/stats", response_model=APIResponse[AdminStatsResponse], summary="管理仪表盘统计")
async def get_admin_stats(
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[AdminStatsResponse]:
    """获取管理仪表盘的汇总统计数据（仅管理员）。"""
    from datetime import datetime, timezone

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 总用户数
    user_count_stmt = select(func.count(User.id)).where(User.is_deleted == False)
    user_count = (await db.execute(user_count_stmt)).scalar_one()

    # 总对话数
    conv_count_stmt = select(func.count(Conversation.id)).where(Conversation.is_deleted == False)
    conv_count = (await db.execute(conv_count_stmt)).scalar_one()

    # 总消息数 & Token 总量
    msg_stmt = select(
        func.count(Message.id),
        func.coalesce(func.sum(Message.token_count), 0),
    ).where(Message.is_deleted == False)
    msg_result = (await db.execute(msg_stmt)).one()
    total_messages = msg_result[0]
    total_tokens = int(msg_result[1])

    # 今日 Token 消耗
    today_token_stmt = (
        select(func.coalesce(func.sum(Message.token_count), 0))
        .where(
            Message.is_deleted == False,
            Message.created_at >= today_start,
        )
    )
    tokens_today = int((await db.execute(today_token_stmt)).scalar_one())

    # 今日活跃用户（通过对话）
    active_stmt = (
        select(func.count(func.distinct(Conversation.user_id)))
        .where(
            Conversation.is_deleted == False,
            Conversation.created_at >= today_start,
        )
    )
    active_users_today = (await db.execute(active_stmt)).scalar_one()

    return APIResponse(
        message="获取成功",
        data=AdminStatsResponse(
            total_users=user_count,
            total_conversations=conv_count,
            total_messages=total_messages,
            total_tokens=total_tokens,
            active_users_today=active_users_today,
            tokens_today=tokens_today,
        ),
    )
