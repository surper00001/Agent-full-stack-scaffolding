"""
知识库相关 Pydantic Schema。
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---- 知识库请求 ----
class CreateKnowledgeBaseRequest(BaseModel):
    """创建知识库请求。"""

    name: str = Field(min_length=1, max_length=255, description="知识库名称")
    description: str | None = Field(default=None, max_length=2000, description="描述")
    chunk_size: int = Field(default=500, ge=100, le=4000, description="分块大小（字符数）")
    chunk_overlap: int = Field(default=50, ge=0, le=500, description="分块重叠（字符数）")
    embedding_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B", max_length=255, description="Embedding 模型"
    )
    reranker_model: str = Field(
        default="Qwen/Qwen3-Reranker-0.6B", max_length=255, description="Reranker 模型"
    )


class UpdateKnowledgeBaseRequest(BaseModel):
    """更新知识库请求。"""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    chunk_size: int | None = Field(default=None, ge=100, le=4000)
    chunk_overlap: int | None = Field(default=None, ge=0, le=500)
    embedding_model: str | None = Field(default=None, max_length=255)
    reranker_model: str | None = Field(default=None, max_length=255)


class KBSearchRequest(BaseModel):
    """知识库搜索请求。"""

    query: str = Field(min_length=1, max_length=4096, description="搜索查询")
    top_k: int = Field(default=5, ge=1, le=50, description="返回结果数")
    filters: dict[str, Any] | None = Field(
        default=None, description="过滤条件: {file_type, document_id, chunk_type}"
    )
    rerank: bool = Field(default=True, description="是否启用重排序")


# ---- 知识库响应 ----
class KnowledgeBaseResponse(BaseModel):
    """知识库详情响应。"""

    id: str
    name: str
    description: str | None
    user_id: str
    chunk_size: int
    chunk_overlap: int
    embedding_model: str
    reranker_model: str
    document_count: int
    total_chunks: int
    total_size_bytes: int
    status: str
    created_at: datetime
    updated_at: datetime
    # 索引一致性（由详情接口附加，非 ORM 字段）
    indexed_model: str | None = Field(default=None, description="向量库中记录的 Embedding 模型")
    needs_reindex: bool = Field(default=False, description="是否需要重建索引")
    server_embedding_model: str | None = Field(
        default=None, description="服务端 .env 默认 Embedding 模型"
    )
    server_reranker_model: str | None = Field(
        default=None, description="服务端 .env 默认 Reranker 模型"
    )
    models_differ_from_env: bool = Field(
        default=False, description="知识库绑定的模型是否与服务端默认不一致"
    )

    model_config = {"from_attributes": True}


class KnowledgeBaseListItem(BaseModel):
    """知识库列表项（精简）。"""

    id: str
    name: str
    description: str | None
    document_count: int
    total_chunks: int
    total_size_bytes: int
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KBDocumentResponse(BaseModel):
    """文档详情响应。"""

    id: str
    knowledge_base_id: str
    filename: str
    file_size: int
    file_type: str
    page_count: int
    chunk_count: int
    status: str
    error_message: str | None
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata_")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class KBDocumentListItem(BaseModel):
    """文档列表项（精简）。"""

    id: str
    filename: str
    file_size: int
    file_type: str
    page_count: int
    chunk_count: int
    status: str
    error_message: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class KBChunkResponse(BaseModel):
    """分块详情响应。"""

    id: str
    document_id: str
    content: str
    chunk_index: int
    page_start: int
    page_end: int
    chunk_type: str
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata_")

    model_config = {"from_attributes": True, "populate_by_name": True}


class KBSearchResultItem(BaseModel):
    """搜索结果项——包含分块信息 + 匹配分数 + 源文件上下文。"""

    chunk_id: str
    document_id: str
    content: str
    expanded_content: str | None = Field(
        default=None, description="父块扩展上下文（默认可选展开）"
    )
    chunk_type: str  # text | table | image
    page_start: int
    page_end: int
    score: float = Field(description="匹配分数（0-1，重排序后）")
    document_filename: str = Field(description="源文件名")
    document_file_type: str = Field(description="源文件类型")
    metadata_: dict[str, Any] | None = Field(default=None, alias="metadata_")
    # 扩展上下文：前后相邻 chunk 的内容
    context_before: str | None = Field(default=None, description="前一分块内容")
    context_after: str | None = Field(default=None, description="后一分块内容")

    model_config = {"populate_by_name": True}


class KBSearchResponse(BaseModel):
    """搜索响应。"""

    query: str
    results: list[KBSearchResultItem]
    total_found: int = Field(description="向量检索返回总数（重排前）")
    reranked: bool = Field(description="是否经过重排序")


class KBPageContent(BaseModel):
    """文档页面内容——用于文档查看器按页展示。"""

    page_number: int
    page_width: float | None = Field(default=None, description="PDF 页宽（点）")
    page_height: float | None = Field(default=None, description="PDF 页高（点）")
    text_blocks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="文本块: [{type: text|table|image, content, bbox, table_html, image_url}]"
    )
    has_content: bool = Field(
        default=False,
        description="该页是否有已提取的结构化内容",
    )


class KBDocumentViewResponse(BaseModel):
    """文档查看响应——按页展示完整内容。"""

    document_id: str
    filename: str
    file_type: str
    total_pages: int
    pages: list[KBPageContent]
    doc_category: str | None = None
    doc_category_label: str | None = None


class KBDocumentPageResponse(BaseModel):
    """单页查看响应——按需加载，避免全量传输。"""

    document_id: str
    filename: str
    file_type: str
    total_pages: int
    page: KBPageContent
    doc_category: str | None = None
    doc_category_label: str | None = None


class KBPageMetaItem(BaseModel):
    """页面元数据条目——用于页码导航。"""

    page_number: int
    has_content: bool


class KBDocumentPagesMetaResponse(BaseModel):
    """文档页面元数据——轻量级，仅用于页码导航。"""

    document_id: str
    filename: str
    file_type: str
    total_pages: int
    pages: list[KBPageMetaItem]
    doc_category: str | None = None
    doc_category_label: str | None = None


class KBUploadResponse(BaseModel):
    """文档上传响应。"""

    document_id: str
    filename: str
    file_size: int
    file_type: str
    status: str
    message: str


class KBProcessProgressResponse(BaseModel):
    """文档处理进度响应——含每阶段具体数字。"""

    document_id: str
    stage: str = Field(description="当前阶段: uploaded|analyzing|parsing|chunking|embedding|indexing|ready|error")
    stage_label: str = Field(description="阶段描述（含具体数字，前端直接展示）")
    percentage: float = Field(description="总体进度百分比 0~100")
    estimated_seconds: float | None = Field(default=None, description="预估剩余秒数")
    file_size_bytes: int = Field(default=0)
    error_message: str | None = Field(default=None)
    # 富详情
    total_pages: int = Field(default=0, description="文档总页数")
    parsed_pages: int = Field(default=0, description="已解析页数")
    text_blocks: int = Field(default=0, description="识别到的文本块数量")
    table_blocks: int = Field(default=0, description="识别到的表格数量")
    image_blocks: int = Field(default=0, description="识别到的图片数量")
    total_chunks: int = Field(default=0, description="总分块数")
    embedded_chunks: int = Field(default=0, description="已向量化的分块数")
