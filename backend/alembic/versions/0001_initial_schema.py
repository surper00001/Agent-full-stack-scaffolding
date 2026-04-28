"""initial_schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-22

Initial schema: all 6 tables with indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # tenants
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), unique=True, nullable=False, index=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("username", sa.String(50), unique=True, nullable=False, index=True),
        sa.Column("phone", sa.String(20), unique=True, nullable=True, index=True),
        sa.Column("email", sa.String(255), unique=True, nullable=True, index=True),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # refresh_tokens
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("token_hash", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_revoked", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    # conversations
    op.create_table(
        "conversations",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("title", sa.String(512), nullable=False, server_default="新对话"),
        sa.Column("agent_type", sa.String(128), nullable=False, server_default="default"),
        sa.Column("message_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("user_id", sa.String(64), nullable=True, index=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # messages
    op.create_table(
        "messages",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("token_count", sa.Integer, nullable=True),
        sa.Column("metadata_", sa.Text, nullable=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # agent_configs
    op.create_table(
        "agent_configs",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("agent_type", sa.String(64), nullable=False, index=True),
        sa.Column("system_prompt", sa.Text, nullable=False),
        sa.Column("model_name", sa.String(128), nullable=False, server_default="gpt-4o"),
        sa.Column("temperature", sa.Float, nullable=False, server_default=sa.text("0.7")),
        sa.Column("max_tokens", sa.Integer, nullable=True),
        sa.Column("tools", sa.Text, nullable=True),
        sa.Column("knowledge_base_ids", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("metadata_", sa.Text, nullable=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # Cursor pagination index for messages
    op.create_index(
        "idx_messages_cursor",
        "messages",
        ["conversation_id", "created_at"],
        postgresql_where=sa.text("is_deleted = 0"),
    )


def downgrade() -> None:
    op.drop_index("idx_messages_cursor", table_name="messages")
    op.drop_table("agent_configs")
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("refresh_tokens")
    op.drop_table("users")
    op.drop_table("tenants")
