"""add_knowledge_base_tables

Revision ID: 0002_kb
Revises: 0001_initial
Create Date: 2026-05-24

Knowledge base tables: knowledge_bases, kb_documents, kb_chunks.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0002_kb"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # knowledge_bases
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("user_id", sa.String(64), nullable=False, index=True),
        sa.Column("chunk_size", sa.Integer, nullable=False, server_default=sa.text("500")),
        sa.Column("chunk_overlap", sa.Integer, nullable=False, server_default=sa.text("50")),
        sa.Column("embedding_model", sa.String(255), nullable=False, server_default="BAAI/bge-large-zh-v1.5"),
        sa.Column("reranker_model", sa.String(255), nullable=False, server_default="BAAI/bge-reranker-v2-m3"),
        sa.Column("document_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("total_chunks", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("total_size_bytes", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # kb_documents
    op.create_table(
        "kb_documents",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("knowledge_base_id", sa.String(36),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("stored_path", sa.String(1024), nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("page_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("chunk_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False, server_default="uploading"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("metadata_", JSONB, nullable=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # kb_chunks
    op.create_table(
        "kb_chunks",
        sa.Column("id", sa.String(36), primary_key=True, index=True),
        sa.Column("document_id", sa.String(36),
                  sa.ForeignKey("kb_documents.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("knowledge_base_id", sa.String(36),
                  sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("page_start", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("page_end", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("chunk_type", sa.String(32), nullable=False, server_default="text"),
        sa.Column("parent_chunk_id", sa.String(64), nullable=True, index=True),
        sa.Column("vector_id", sa.String(256), nullable=True),
        sa.Column("metadata_", JSONB, nullable=True),
        sa.Column("tenant_id", sa.String(64), nullable=False, index=True, server_default="default"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("0")),
    )

    # Index for parent-child chunk lookups
    op.create_index(
        "idx_kb_chunks_doc_index",
        "kb_chunks",
        ["document_id", "chunk_index"],
        postgresql_where=sa.text("is_deleted = 0"),
    )


def downgrade() -> None:
    op.drop_index("idx_kb_chunks_doc_index", table_name="kb_chunks")
    op.drop_table("kb_chunks")
    op.drop_table("kb_documents")
    op.drop_table("knowledge_bases")
