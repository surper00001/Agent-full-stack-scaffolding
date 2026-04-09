"""
会话领域模型。

记录用户与 Agent 之间的对话历史，
每条消息关联一个 conversation，按时间顺序排列。
"""

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import BaseModel


class Conversation(BaseModel):
    """会话表 - 一次完整的对话。"""

    __tablename__ = "conversations"

    title: Mapped[str] = mapped_column(
        String(512), default="新对话", comment="会话标题"
    )
    agent_type: Mapped[str] = mapped_column(
        String(128), default="default", comment="使用的 Agent 类型"
    )
    message_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="消息数量"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", comment="状态: active | archived"
    )

    # 关联消息
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", lazy="selectin", order_by="Message.created_at"
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title={self.title})>"


class Message(BaseModel):
    """消息表 - 对话中的一条消息。"""

    __tablename__ = "messages"

    conversation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属会话 ID",
    )
    role: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="角色: user | assistant | system | tool"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="消息内容"
    )
    token_count: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Token 数量（估算）"
    )
    metadata_: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="附加元数据（JSON）"
    )

    # 关联会话
    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="messages"
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role})>"
