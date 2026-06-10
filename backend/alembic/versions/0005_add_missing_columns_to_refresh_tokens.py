"""add missing columns to refresh_tokens

Revision ID: 0005
Revises: 0004_add_token_quota_to_users
Create Date: 2026-06-10

refresh_tokens 表在 0001 迁移时遗漏了 BaseModel mixin 提供的列：
- updated_at (TimestampMixin)
- tenant_id (TenantIsolationMixin)
- is_deleted (SoftDeleteMixin)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: Union[str, None] = "0004_add_token_quota_to_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "refresh_tokens",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("tenant_id", sa.String(64), nullable=False, server_default="default"),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )
    # 为 tenant_id 添加索引（匹配其他表的隔离模式）
    op.create_index(op.f("ix_refresh_tokens_tenant_id"), "refresh_tokens", ["tenant_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_refresh_tokens_tenant_id"), table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "is_deleted")
    op.drop_column("refresh_tokens", "tenant_id")
    op.drop_column("refresh_tokens", "updated_at")
