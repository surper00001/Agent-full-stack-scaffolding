"""Token 统计服务层 — 聚合查询 Token 消耗数据。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.domain.conversation import Conversation, Message


class TokenStatsService:
    """Token 统计服务（仅管理员使用）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_tenant_token_usage(self, days: int = 30) -> dict:
        """获取租户级别的 Token 用量统计。

        Returns:
            dict with: quota, used, daily_usage, by_agent, recent_records, compared_to_last_month
        """
        now = datetime.now(UTC)
        since = now - timedelta(days=days)
        prev_since = since - timedelta(days=days)  # 上期对比

        # 总量（当期）
        total_stmt = (
            select(func.coalesce(func.sum(Message.token_count), 0))
            .where(
                Message.is_deleted.is_(False),
                Message.created_at >= since,
            )
        )
        total_used = int((await self._session.execute(total_stmt)).scalar_one() or 0)

        # 上期总量（用于环比）
        prev_stmt = (
            select(func.coalesce(func.sum(Message.token_count), 0))
            .where(
                Message.is_deleted.is_(False),
                Message.created_at >= prev_since,
                Message.created_at < since,
            )
        )
        prev_used = int((await self._session.execute(prev_stmt)).scalar_one() or 0)

        # 环比变化百分比
        if prev_used > 0:
            compared_to_last_month = int((total_used - prev_used) / prev_used * 100)
        else:
            compared_to_last_month = 100 if total_used > 0 else 0

        # 按日聚合
        daily_stmt = (
            select(
                func.date(Message.created_at).label("date"),
                func.coalesce(func.sum(Message.token_count), 0).label("tokens"),
            )
            .where(
                Message.is_deleted.is_(False),
                Message.created_at >= since,
            )
            .group_by(text("date"))
            .order_by(text("date"))
        )
        daily_result = await self._session.execute(daily_stmt)
        daily_map = {str(row.date): row.tokens for row in daily_result.all()}

        daily_usage = []
        for i in range(days):
            d = (since + timedelta(days=i)).strftime("%Y-%m-%d")
            daily_usage.append({"date": d, "count": daily_map.get(d, 0)})

        # 按 Agent 类型聚合
        agent_stmt = (
            select(
                Conversation.agent_type,
                func.coalesce(func.sum(Message.token_count), 0).label("tokens"),
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.is_deleted.is_(False),
                Conversation.is_deleted.is_(False),
                Message.created_at >= since,
            )
            .group_by(Conversation.agent_type)
            .order_by(text("tokens DESC"))
        )
        agent_result = await self._session.execute(agent_stmt)
        agent_rows = agent_result.all()
        agent_total = sum(row.tokens for row in agent_rows) or 1
        by_agent = [
            {
                "agent_name": row.agent_type,
                "count": row.tokens,
                "percentage": round(row.tokens / agent_total * 100, 1),
            }
            for row in agent_rows
        ]

        # 最近记录
        recent_stmt = (
            select(
                Message.created_at,
                Message.token_count,
                Conversation.agent_type,
            )
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                Message.is_deleted.is_(False),
                Conversation.is_deleted.is_(False),
                Message.created_at >= since,
            )
            .order_by(Message.created_at.desc())
            .limit(20)
        )
        recent_result = await self._session.execute(recent_stmt)
        recent_records = [
            {
                "date": row.created_at.isoformat(),
                "tokens": row.token_count or 0,
                "agent_name": row.agent_type,
            }
            for row in recent_result.all()
        ]

        return {
            "quota": 1_000_000,
            "used": total_used,
            "daily_usage": daily_usage,
            "by_agent": by_agent,
            "recent_records": recent_records,
            "compared_to_last_month": compared_to_last_month,
        }
