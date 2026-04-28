"""add_conversation_kb_id

Revision ID: 0003_conv_kb
Revises: 0002_kb
Create Date: 2026-05-24

为 conversations 表增加 knowledge_base_id 字段。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0003_conv_kb"
down_revision: Union[str, None] = "0002_kb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "knowledge_base_id",
            sa.String(64),
            nullable=True,
            comment="绑定的知识库 ID",
        ),
    )
    op.create_index(
        op.f("ix_conversations_knowledge_base_id"),
        "conversations",
        ["knowledge_base_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_conversations_knowledge_base_id"), table_name="conversations")
    op.drop_column("conversations", "knowledge_base_id")
