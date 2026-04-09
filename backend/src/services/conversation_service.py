"""
会话服务层。

处理聊天会话与消息的业务逻辑。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions import ConversationNotFoundError
from src.db.repository import BaseRepository
from src.models.domain.conversation import Conversation, Message


class ConversationService:
    """会话业务服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._conv_repo = BaseRepository[Conversation](Conversation, session)
        self._msg_repo = BaseRepository[Message](Message, session)

    # ---- 会话 CRUD ----

    async def create_conversation(
        self,
        title: str = "新对话",
        agent_type: str = "default",
        tenant_id: str = "default",
    ) -> Conversation:
        """创建新会话。"""
        conv = Conversation(
            title=title,
            agent_type=agent_type,
            tenant_id=tenant_id,
        )
        return await self._conv_repo.create(conv)

    async def get_conversation(
        self, conv_id: str, tenant_id: str
    ) -> Conversation:
        """获取会话详情（含消息）。"""
        conv = await self._conv_repo.get_by_id_with_tenant(conv_id, tenant_id)
        if conv is None:
            raise ConversationNotFoundError(conv_id)
        return conv

    async def list_conversations(
        self,
        tenant_id: str,
        skip: int = 0,
        limit: int = 50,
    ) -> list[Conversation]:
        """获取会话列表。"""
        return await self._conv_repo.list_all(
            tenant_id=tenant_id, skip=skip, limit=limit
        )

    async def delete_conversation(self, conv_id: str, tenant_id: str) -> bool:
        """软删除会话。"""
        conv = await self.get_conversation(conv_id, tenant_id)
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
        """向会话添加一条消息。"""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            token_count=token_count,
            tenant_id=tenant_id,
        )
        result = await self._msg_repo.create(msg)

        # 更新会话消息计数
        conv = await self._conv_repo.get_by_id(conversation_id)
        if conv:
            conv.message_count = (conv.message_count or 0) + 1
            await self._conv_repo.update(conv)

        return result

    async def get_messages(
        self,
        conversation_id: str,
        tenant_id: str,
        skip: int = 0,
        limit: int = 200,
    ) -> list[Message]:
        """获取会话的消息列表。"""
        return await self._msg_repo.list_all(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            skip=skip,
            limit=limit,
        )
