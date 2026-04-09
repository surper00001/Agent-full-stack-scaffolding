"""
租户领域模型。

支持多租户 SaaS 架构，每个租户拥有独立的数据隔离空间。
"""

from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import BaseModel


class Tenant(BaseModel):
    """租户表 - 代表一个组织或工作空间。"""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="租户名称")
    slug: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True, comment="租户唯一标识符"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="租户描述"
    )
    is_active: Mapped[bool] = mapped_column(
        default=True, nullable=False, comment="是否启用"
    )

    def __repr__(self) -> str:
        return f"<Tenant(id={self.id}, slug={self.slug}, name={self.name})>"
