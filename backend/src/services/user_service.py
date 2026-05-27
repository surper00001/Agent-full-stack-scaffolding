"""用户管理服务层 — 管理员视角的用户 CRUD 和统计。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, cast, func, or_, select, String, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import AppException, NotFoundError, UserNotFoundError
from src.db.repository import BaseRepository
from src.models.domain.conversation import Conversation, Message
from src.models.domain.user import User


class UserService:
    """用户管理服务（仅管理员使用）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._user_repo = BaseRepository[User](User, session)
        self._conv_repo = BaseRepository[Conversation](Conversation, session)
        self._msg_repo = BaseRepository[Message](Message, session)
        self._session = session

    # ---- 用户列表 ----

    async def list_users(
        self,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
    ) -> tuple[list[dict], int]:
        """分页查询用户列表，含对话数和 Token 总量聚合。"""
        skip = (page - 1) * page_size

        # 子查询：每个用户的对话数
        conv_count_subq = (
            select(func.count(Conversation.id))
            .where(
                and_(
                    Conversation.user_id == cast(User.id, String),
                    Conversation.is_deleted == False,
                )
            )
            .correlate(User)
            .scalar_subquery()
            .label("conversation_count")
        )

        # 子查询：每个用户的 Token 总量（通过对话-消息关联）
        token_subq = (
            select(func.coalesce(func.sum(Message.token_count), 0))
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                and_(
                    Conversation.user_id == cast(User.id, String),
                    Message.is_deleted == False,
                    Conversation.is_deleted == False,
                )
            )
            .correlate(User)
            .scalar_subquery()
            .label("total_tokens")
        )

        conditions = [User.is_deleted == False]
        if search:
            search_term = f"%{search}%"
            conditions.append(
                or_(
                    User.username.ilike(search_term),
                    User.email.ilike(search_term),
                    User.phone.ilike(search_term),
                )
            )

        # 查询总数
        count_stmt = (
            select(func.count())
            .select_from(User)
            .where(and_(*conditions))
        )
        total_result = await self._session.execute(count_stmt)
        total = total_result.scalar_one()

        # 查询列表
        stmt = (
            select(
                User,
                conv_count_subq,
                token_subq,
            )
            .where(and_(*conditions))
            .order_by(User.created_at.desc())
            .offset(skip)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        items = [
            {
                "id": str(row.User.id),
                "username": row.User.username,
                "email": row.User.email,
                "phone": row.User.phone,
                "role": row.User.role,
                "is_active": row.User.is_active,
                "is_verified": row.User.is_verified,
                "conversation_count": row.conversation_count,
                "total_tokens": row.total_tokens,
                "created_at": row.User.created_at,
            }
            for row in rows
        ]

        return items, total

    # ---- 用户详情 ----

    async def get_user_detail(self, user_id: str) -> dict:
        """获取用户详情，含统计数据和最近对话。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()

        # 对话总数
        conv_count_stmt = (
            select(func.count(Conversation.id))
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.is_deleted == False,
                )
            )
        )
        conv_count_result = await self._session.execute(conv_count_stmt)
        conversation_count = conv_count_result.scalar_one()

        # Token 总量
        token_stmt = (
            select(func.coalesce(func.sum(Message.token_count), 0))
            .select_from(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Message.is_deleted == False,
                    Conversation.is_deleted == False,
                )
            )
        )
        token_result = await self._session.execute(token_stmt)
        total_tokens = token_result.scalar_one()

        # 最近 10 个对话（含 Token）
        recent_stmt = (
            select(
                Conversation,
                func.coalesce(func.sum(Message.token_count), 0).label("conv_tokens"),
            )
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.is_deleted == False,
                )
            )
            .group_by(Conversation.id)
            .order_by(Conversation.created_at.desc())
            .limit(10)
        )
        recent_result = await self._session.execute(recent_stmt)
        recent_rows = recent_result.all()

        recent_conversations = [
            {
                "id": str(row.Conversation.id),
                "title": row.Conversation.title,
                "agent_type": row.Conversation.agent_type,
                "message_count": row.Conversation.message_count or 0,
                "status": row.Conversation.status,
                "total_tokens": row.conv_tokens,
                "knowledge_base_name": None,
                "created_at": row.Conversation.created_at,
                "updated_at": row.Conversation.updated_at,
            }
            for row in recent_rows
        ]

        return {
            "id": str(user.id),
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "role": user.role,
            "is_active": user.is_active,
            "is_verified": user.is_verified,
            "conversation_count": conversation_count,
            "total_tokens": total_tokens,
            "token_quota": getattr(user, "token_quota", None),
            "created_at": user.created_at,
            "updated_at": user.updated_at,
            "recent_conversations": recent_conversations,
        }

    # ---- 用户对话列表 ----

    async def get_user_conversations(
        self,
        user_id: str,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict], int]:
        """获取某用户的所有对话（含 Token 消耗）。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()

        skip = (page - 1) * page_size

        # 总数
        count_stmt = (
            select(func.count(Conversation.id))
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.is_deleted == False,
                )
            )
        )
        count_result = await self._session.execute(count_stmt)
        total = count_result.scalar_one()

        # 列表
        stmt = (
            select(
                Conversation,
                func.coalesce(func.sum(Message.token_count), 0).label("conv_tokens"),
            )
            .outerjoin(Message, Message.conversation_id == Conversation.id)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.is_deleted == False,
                )
            )
            .group_by(Conversation.id)
            .order_by(Conversation.created_at.desc())
            .offset(skip)
            .limit(page_size)
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        items = [
            {
                "id": str(row.Conversation.id),
                "title": row.Conversation.title,
                "agent_type": row.Conversation.agent_type,
                "message_count": row.Conversation.message_count or 0,
                "status": row.Conversation.status,
                "total_tokens": row.conv_tokens,
                "knowledge_base_name": None,
                "created_at": row.Conversation.created_at,
                "updated_at": row.Conversation.updated_at,
            }
            for row in rows
        ]

        return items, total

    # ---- Token 消耗明细 ----

    async def get_user_token_usage(
        self,
        user_id: str,
    ) -> dict:
        """获取用户的 Token 消耗明细（按对话聚合）。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()

        # 按对话聚合 Token
        stmt = (
            select(
                Conversation.id,
                Conversation.title,
                func.count(Message.id).label("msg_count"),
                func.coalesce(func.sum(Message.token_count), 0).label("tokens"),
                Conversation.created_at,
            )
            .join(Message, Message.conversation_id == Conversation.id)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Conversation.is_deleted == False,
                    Message.is_deleted == False,
                )
            )
            .group_by(Conversation.id)
            .order_by(Conversation.created_at.desc())
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        by_conversation = [
            {
                "conversation_id": str(row.id),
                "conversation_title": row.title,
                "tokens": row.tokens,
                "message_count": row.msg_count,
                "created_at": row.created_at,
            }
            for row in rows
        ]

        total_tokens = sum(item["tokens"] for item in by_conversation)

        return {
            "user_id": user_id,
            "username": user.username,
            "total_tokens": total_tokens,
            "daily": [],  # 按日聚合在单独的端点返回
            "by_conversation": by_conversation,
        }

    async def get_user_token_trend(
        self,
        user_id: str,
        days: int = 7,
    ) -> list[dict]:
        """获取用户 Token 使用趋势（按日聚合）。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()

        since = datetime.now(timezone.utc) - timedelta(days=days)

        # 按日期聚合 Token 消耗
        stmt = (
            select(
                func.date(Message.created_at).label("date"),
                func.coalesce(func.sum(Message.token_count), 0).label("tokens"),
            )
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(
                and_(
                    Conversation.user_id == user_id,
                    Message.created_at >= since,
                    Message.is_deleted == False,
                    Conversation.is_deleted == False,
                )
            )
            .group_by(text("date"))
            .order_by(text("date"))
        )
        result = await self._session.execute(stmt)
        rows = result.all()

        # 填充缺失日期
        daily_map = {str(row.date): row.tokens for row in rows}
        trend = []
        for i in range(days):
            d = (since + timedelta(days=i)).strftime("%Y-%m-%d")
            trend.append({"date": d, "tokens": daily_map.get(d, 0)})

        return trend

    # ---- 管理操作 ----

    async def delete_user(self, user_id: str) -> bool:
        """软删除用户。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()
        if user.role == "admin":
            raise AppException(
                status_code=400,
                code=40003,
                message="不能删除管理员账户",
            )
        return await self._user_repo.soft_delete(user_id)

    async def delete_user_conversations(self, user_id: str) -> int:
        """清空用户的所有对话（软删除）。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()
        return await self._conv_repo.soft_delete_by_filter(user_id=user_id)

    async def set_token_quota(self, user_id: str, token_quota: int) -> dict:
        """设置用户的 Token 配额。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()

        if not hasattr(user, "token_quota"):
            # 动态添加属性（如果没有该列则会失败，需要 DB 迁移）
            raise AppException(
                status_code=500,
                code=50002,
                message="Token 配额功能需要数据库迁移，请先运行 alembic upgrade head",
            )

        user.token_quota = token_quota
        await self._user_repo.update(user)

        return {
            "user_id": user_id,
            "token_quota": token_quota,
        }

    async def update_user_role(self, user_id: str, role: str) -> dict:
        """更新用户角色。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()

        user.role = role
        await self._user_repo.update(user)

        return {
            "user_id": user_id,
            "role": role,
        }

    async def toggle_user_active(self, user_id: str) -> dict:
        """启用/禁用用户。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None or user.is_deleted:
            raise UserNotFoundError()
        if user.role == "admin":
            raise AppException(
                status_code=400,
                code=40003,
                message="不能禁用管理员账户",
            )

        user.is_active = not user.is_active
        await self._user_repo.update(user)

        return {
            "user_id": user_id,
            "is_active": user.is_active,
        }
