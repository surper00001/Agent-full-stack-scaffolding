"""
数据库基础模型模块。

所有 ORM 模型均继承自 Base，提供统一的：
- 主键 ID（UUID）
- 自动时间戳（created_at / updated_at）
- 软删除标记（is_deleted）
- 多租户隔离字段（tenant_id）
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import UUID, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类。"""

    __abstract__ = True


class TimestampMixin:
    """自动管理 created_at / updated_at 时间戳的混入类。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class UUIDPrimaryKeyMixin:
    """UUID 主键混入类。"""

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )


class TenantIsolationMixin:
    """多租户数据隔离混入类。

    通过 tenant_id 实现行级租户隔离。
    当 multi_tenant_enabled=False 时，所有记录使用默认租户 ID。
    """

    __table_args__ = ()  # 占位，子类可按需扩展

    tenant_id: Mapped[str] = mapped_column(
        String(64),
        default="default",
        nullable=False,
        index=True,
    )


class SoftDeleteMixin:
    """软删除混入类。

    删除操作仅设置 is_deleted=True，不物理删除记录。
    """

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )


class BaseModel(
    Base, UUIDPrimaryKeyMixin, TimestampMixin, TenantIsolationMixin, SoftDeleteMixin
):
    """
    聚合所有混入类的完整基础模型。

    所有业务实体 ORM 模型建议继承此类，以获得统一的字段和约束。
    """

    __abstract__ = True
    __table_args__ = ()  # 实际由子类 override
