"""
会话服务层。

处理聊天会话与消息的业务逻辑，包含 token 感知的消息管理和游标分页。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agents.context_manager import ContextConfig, ContextManager, ContextStrategy, TokenCounter
from src.core.exceptions import ConversationNotFoundError
from src.db.repository import BaseRepository
from src.models.domain.conversation import Conversation, Message
from src.services.conversation_context_store import ConversationContextStore, get_conversation_context_store


def _orm_to_langchain_all(messages: list[Message]) -> list[BaseMessage]:
    """将 ORM 消息列表转换为 LangChain 消息列表，保留所有角色类型。"""
    lc_messages: list[BaseMessage] = []
    for m in messages:
        if m.role == "user":
            lc_messages.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            lc_messages.append(AIMessage(content=m.content))
        elif m.role == "system":
            lc_messages.append(SystemMessage(content=m.content))
        elif m.role == "tool":
            meta = {}
            if m.metadata_:
                try:
                    meta = json.loads(m.metadata_)
                except (json.JSONDecodeError, TypeError):
                    pass
            lc_messages.append(
                ToolMessage(
                    content=m.content,
                    tool_call_id=meta.get("tool_call_id", ""),
                )
            )
    return lc_messages


class ConversationService:
    """会话业务服务。"""

    def __init__(
        self,
        session: AsyncSession,
        context_store: ConversationContextStore | None = None,
    ) -> None:
        self._conv_repo = BaseRepository[Conversation](Conversation, session)
        self._msg_repo = BaseRepository[Message](Message, session)
        self._session = session
        self._context_store = context_store

    # ---- 会话 CRUD ----

    async def create_conversation(
        self,
        title: str = "新对话",
        agent_type: str = "general",
        tenant_id: str = "default",
        user_id: str | None = None,
        knowledge_base_id: str | None = None,
    ) -> Conversation:
        conv = Conversation(
            title=title,
            agent_type=agent_type,
            tenant_id=tenant_id,
            user_id=user_id,
            knowledge_base_id=knowledge_base_id,
        )
        return await self._conv_repo.create(conv)

    async def update_knowledge_base(
        self,
        conv_id: str,
        tenant_id: str,
        knowledge_base_id: str | None,
        user_id: str | None = None,
    ) -> Conversation:
        """更新会话绑定的知识库。"""
        conv = await self.get_conversation(conv_id, tenant_id, user_id)
        conv.knowledge_base_id = knowledge_base_id
        return await self._conv_repo.update(conv)

    async def get_conversation(
        self, conv_id: str, tenant_id: str, user_id: str | None = None
    ) -> Conversation:
        conv = await self._conv_repo.get_by_id_with_tenant(conv_id, tenant_id)
        if conv is None:
            raise ConversationNotFoundError(conv_id)
        if user_id is not None and conv.user_id is not None and conv.user_id != user_id:
            raise ConversationNotFoundError(conv_id)
        return conv

    async def list_conversations(
        self,
        tenant_id: str,
        skip: int = 0,
        limit: int = 50,
        user_id: str | None = None,
    ) -> list[Conversation]:
        filters: dict[str, Any] = {}
        if user_id is not None:
            filters["user_id"] = user_id
        return await self._conv_repo.list_all(
            tenant_id=tenant_id, skip=skip, limit=limit, **filters
        )

    async def count_conversations(
        self,
        tenant_id: str,
        user_id: str | None = None,
    ) -> int:
        """统计会话总数（按租户和可选用户过滤）。"""
        filters: dict[str, Any] = {}
        if user_id is not None:
            filters["user_id"] = user_id
        return await self._conv_repo.count(tenant_id=tenant_id, **filters)

    async def delete_conversation(
        self, conv_id: str, tenant_id: str, user_id: str | None = None
    ) -> bool:
        conv = await self.get_conversation(conv_id, tenant_id, user_id)
        return await self._conv_repo.soft_delete(conv.id)

    # ---- 消息 CRUD ----

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        token_count: int | None = None,
        tenant_id: str = "default",
    ) -> Message:
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            tenant_id=tenant_id,
        )
        result = await self._msg_repo.create(msg)

        conv = await self._conv_repo.get_by_id_with_tenant(conversation_id, tenant_id)
        if conv:
            conv.message_count = (conv.message_count or 0) + 1
            await self._conv_repo.update(conv)

        return result

    async def add_message_with_metadata(
        self,
        conversation_id: str,
        role: str,
        content: str,
        token_count: int | None = None,
        importance: float | None = None,
        metadata: dict[str, Any] | None = None,
        tenant_id: str = "default",
    ) -> Message:
        """添加消息并自动计算 token 计数、存储元数据。"""
        if token_count is None:
            counter = TokenCounter()
            token_count = counter.count_tokens(content)

        merged_meta: dict[str, Any] = dict(metadata or {})
        if importance is not None:
            merged_meta["importance"] = importance

        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            metadata_=json.dumps(merged_meta) if merged_meta else None,
            tenant_id=tenant_id,
        )
        result = await self._msg_repo.create(msg)

        conv = await self._conv_repo.get_by_id_with_tenant(conversation_id, tenant_id)
        if conv:
            conv.message_count = (conv.message_count or 0) + 1
            await self._conv_repo.update(conv)

        # 异步写入向量存储（不阻塞消息保存）
        if self._context_store and role in ("user", "assistant"):
            try:
                await self._context_store.add_message(
                    message_id=result.id,
                    role=role,
                    content=content,
                    conversation_id=conversation_id,
                    tenant_id=tenant_id,
                    metadata=merged_meta,
                )
            except Exception as e:
                logger.debug(f"向量写入失败（不阻塞主流程）: {e}")

        return result

    async def get_messages(
        self,
        conversation_id: str,
        tenant_id: str,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Message]:
        return await self._msg_repo.list_all(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            skip=skip,
            limit=limit,
        )

    async def count_messages(
        self,
        conversation_id: str,
        tenant_id: str,
    ) -> int:
        """统计会话的消息总数。"""
        return await self._msg_repo.count(
            tenant_id=tenant_id, conversation_id=conversation_id
        )

    async def get_messages_cursor(
        self,
        conversation_id: str,
        tenant_id: str,
        cursor: str | None = None,
        limit: int = 50,
        direction: str = "backward",
    ) -> tuple[list[Message], str | None]:
        """基于游标的消息分页查询。

        Args:
            cursor: ISO 格式时间戳游标
            limit: 每页数量
            direction: backward=加载更早消息, forward=加载更新消息

        Returns:
            (messages, next_cursor) — next_cursor 为 None 表示无更多数据
        """
        conditions = [
            Message.is_deleted == False,
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
        ]

        if cursor and direction == "backward":
            conditions.append(Message.created_at < cursor)
        elif cursor and direction == "forward":
            conditions.append(Message.created_at > cursor)

        order = (
            Message.created_at.desc() if direction == "backward"
            else Message.created_at.asc()
        )

        stmt = (
            select(Message)
            .where(and_(*conditions))
            .order_by(order)
            .limit(limit + 1)
        )
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        next_cursor = rows[-1].created_at.isoformat() if rows and has_more else None

        if direction == "backward":
            rows.reverse()

        return rows, next_cursor

    async def get_context_info(
        self,
        conversation_id: str,
        tenant_id: str,
    ) -> dict[str, Any]:
        """获取会话的上下文使用统计。"""
        orm_messages = await self.get_messages(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        counter = TokenCounter()
        total_tokens = 0
        for msg in orm_messages:
            count = msg.token_count or counter.count_tokens(msg.content)
            total_tokens += count

        from src.core.config import get_settings

        settings = get_settings()
        max_context = settings.context_max_tokens

        return {
            "total_messages": len(orm_messages),
            "total_tokens": total_tokens,
            "max_context": max_context,
            "usage_ratio": total_tokens / max_context if max_context > 0 else 0,
            "model": "default",
        }

    async def get_context_optimized_messages(
        self,
        conversation_id: str,
        tenant_id: str,
        strategy: ContextStrategy = ContextStrategy.HYBRID,
        token_limit: int = 128_000,
    ) -> tuple[list[BaseMessage], Any]:
        """获取经过上下文优化的消息（供 Agent 使用）。"""
        orm_messages = await self.get_messages(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
        )
        lc_messages = _orm_to_langchain_all(orm_messages)

        manager = ContextManager(
            config=ContextConfig(strategy=strategy, max_tokens=token_limit),
            token_counter=TokenCounter(),
        )
        optimized = await manager.prepare_context(lc_messages)
        return optimized, manager.stats
