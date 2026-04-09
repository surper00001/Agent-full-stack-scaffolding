"""
向量数据库抽象层。

定义统一的向量存储接口，支持 Chroma、pgvector 等多种后端，
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
    async def delete_by_ids(
        self,
        ids: list[str],
        collection_name: str = "default",
    ) -> bool:
        """按 ID 删除文档。"""
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
