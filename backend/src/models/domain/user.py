"""用户领域模型。"""

from sqlalchemy import BigInteger, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import BaseModel


class User(BaseModel):
    """用户表。"""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True, comment="用户名"
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), unique=True, nullable=True, index=True, comment="手机号"
    )
    email: Mapped[str | None] = mapped_column(
        String(255), unique=True, nullable=True, index=True, comment="邮箱"
    )
    hashed_password: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="密码哈希"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )
    is_verified: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已验证"
    )
    role: Mapped[str] = mapped_column(
        String(16), default="user", nullable=False, comment="角色: admin | user"
    )
    token_quota: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True, comment="Token 配额上限（null=无限制）"
    )

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role})>"
