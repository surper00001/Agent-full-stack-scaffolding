"""
向量数据库抽象层。

定义统一的向量存储接口，支持 Chroma、Qdrant、pgvector 等多种后端，
通过工厂模式根据配置动态选择实现。
"""

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.documents import Document


class BaseVectorStore(ABC):
    """向量数据库抽象基类，定义统一的操作接口。"""

    @abstractmethod
    async def add_documents(
        self,
        documents: list[Document],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> list[str]:
        """添加文档到向量库，返回文档 ID 列表。"""
        ...

    @abstractmethod
    async def add_documents_with_embeddings(
        self,
        documents: list[Document],
        embeddings: list[list[float]],
        ids: list[str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> None:
        """添加已向量化的文档，跳过内部 embedding 计算。"""
        ...

    @abstractmethod
    async def similarity_search(
        self,
        query: str,
        collection_name: str = "default",
        tenant_id: str = "default",
        top_k: int = 5,
        **kwargs: Any,
    ) -> list[Document]:
        """相似度检索，返回最相关的文档列表。"""
        ...

    @abstractmethod
    async def similarity_search_by_vector(
        self,
        query_embedding: list[float],
        collection_name: str = "default",
        tenant_id: str = "default",
        top_k: int = 5,
        filter: dict[str, Any] | None = None,  # noqa: A002
    ) -> list[Document]:
        """使用预计算 query 向量检索，与索引路径保持一致。"""
        ...

    @abstractmethod
    async def get_collection_embedding_model(
        self, collection_name: str, tenant_id: str = "default"
    ) -> str | None:
        """读取 collection 中记录的 embedding 模型版本。"""
        ...

    @abstractmethod
    async def delete_by_ids(
        self,
        ids: list[str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> bool:
        """按 ID 删除文档。"""
        ...

    @abstractmethod
    async def delete_by_filter(
        self,
        where: dict[str, str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> bool:
        """按 metadata 条件删除（如 document_id）。"""
        ...

    @abstractmethod
    async def delete_collection(
        self,
        collection_name: str,
        tenant_id: str = "default",
    ) -> bool:
        """删除整个集合。"""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """检查向量数据库连接状态。"""
        ...


def create_vector_store(embedding_function: Any = None) -> BaseVectorStore:
    """工厂函数：根据配置创建向量存储实例。

    Usage:
        store = create_vector_store(embedding_function=my_embeddings.to_langchain())
    """
    from src.core.config import get_settings

    settings = get_settings()
    store_type = settings.vector_store_type

    if store_type == "qdrant":
        from src.vectorstore.qdrant_store import QdrantVectorStore

        return QdrantVectorStore(embedding_function=embedding_function)

    if store_type == "pgvector":
        raise NotImplementedError("pgvector 向量存储尚未实现")

    # 默认 Chroma
    from src.vectorstore.chroma_store import ChromaVectorStore

    return ChromaVectorStore(embedding_function=embedding_function)
