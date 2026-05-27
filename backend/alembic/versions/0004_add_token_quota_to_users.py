"""Add token_quota column to users table.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("token_quota", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "token_quota")
