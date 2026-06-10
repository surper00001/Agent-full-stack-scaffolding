"""
知识库领域模型。

KnowledgeBase → 用户的知识库
KBDocument  → 上传的源文件
KBChunk     → 文档分块（文本/表格/图片）
"""

from typing import Any

from sqlalchemy import JSON, UUID, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import BaseModel


class KnowledgeBase(BaseModel):
    """知识库——每个用户可创建多个知识库。"""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="知识库名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述")
    user_id: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True, comment="所属用户 ID"
    )
    chunk_size: Mapped[int] = mapped_column(
        Integer, default=500, comment="分块大小（字符数）"
    )
    chunk_overlap: Mapped[int] = mapped_column(
        Integer, default=50, comment="分块重叠（字符数）"
    )
    embedding_model: Mapped[str] = mapped_column(
        String(255), default="Qwen/Qwen3-Embedding-0.6B", comment="Embedding 模型"
    )
    reranker_model: Mapped[str] = mapped_column(
        String(255), default="Qwen/Qwen3-Reranker-0.6B", comment="Reranker 模型"
    )
    document_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="文档数量"
    )
    total_chunks: Mapped[int] = mapped_column(
        Integer, default=0, comment="总分块数"
    )
    total_size_bytes: Mapped[int] = mapped_column(
        Integer, default=0, comment="总文件大小（字节）"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="active", comment="状态: active | indexing | error"
    )

    documents: Mapped[list["KBDocument"]] = relationship(
        "KBDocument", back_populates="knowledge_base", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, name={self.name}, docs={self.document_count})>"


class KBDocument(BaseModel):
    """知识库文档——上传的源文件记录。"""

    __tablename__ = "kb_documents"

    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属知识库 ID"
    )
    filename: Mapped[str] = mapped_column(
        String(512), nullable=False, comment="原始文件名"
    )
    stored_path: Mapped[str] = mapped_column(
        String(1024), nullable=False, comment="存档路径"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, default=0, comment="文件大小（字节）"
    )
    file_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="文件类型: pdf|docx|doc|txt|md|png|jpg|..."
    )
    page_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="页数（图片为 1）"
    )
    chunk_count: Mapped[int] = mapped_column(
        Integer, default=0, comment="分块数量"
    )
    status: Mapped[str] = mapped_column(
        String(32), default="uploading",
        comment="状态: uploading|processing|ready|error"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="错误信息"
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(  # type: ignore[type-arg]
        JSON, nullable=True, comment="扩展元数据（作者、标题、OCR 结果等）"
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship(
        "KnowledgeBase", back_populates="documents"
    )
    chunks: Mapped[list["KBChunk"]] = relationship(
        "KBChunk", back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KBDocument(id={self.id}, file={self.filename}, status={self.status})>"


class KBChunk(BaseModel):
    """文档分块——检索的最小单元。"""

    __tablename__ = "kb_chunks"

    document_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("kb_documents.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属文档 ID"
    )
    knowledge_base_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="所属知识库 ID"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="分块文本内容"
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="在文档中的序号"
    )
    page_start: Mapped[int] = mapped_column(
        Integer, default=1, comment="起始页码"
    )
    page_end: Mapped[int] = mapped_column(
        Integer, default=1, comment="结束页码"
    )
    chunk_type: Mapped[str] = mapped_column(
        String(32), default="text", comment="分块类型: text|table|image"
    )
    parent_chunk_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="父块 ID（父子分块模式）"
    )
    vector_id: Mapped[str | None] = mapped_column(
        String(256), nullable=True, comment="向量数据库中的 ID"
    )
    metadata_: Mapped[dict[str, Any] | None] = mapped_column(  # type: ignore[type-arg]
        JSON, nullable=True, comment="位置信息: {bbox, section, table_html, image_path, ...}"
    )

    document: Mapped["KBDocument"] = relationship("KBDocument", back_populates="chunks")

    def __repr__(self) -> str:
        return f"<KBChunk(id={self.id}, doc={self.document_id}, idx={self.chunk_index}, type={self.chunk_type})>"
