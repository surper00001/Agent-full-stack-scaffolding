"""Refresh Token 领域模型。"""

from datetime import UTC, datetime

from sqlalchemy import UUID, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, UUIDPrimaryKeyMixin


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """Refresh Token 表 - 用于双 Token 认证机制。"""

    __tablename__ = "refresh_tokens"

    token_hash: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True, comment="Token 哈希值"
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="过期时间"
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已撤销"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
        nullable=False,
    )

    @property
    def is_expired(self) -> bool:
        return datetime.now(UTC) > self.expires_at

    @property
    def is_valid(self) -> bool:
        return not self.is_revoked and not self.is_expired
