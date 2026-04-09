"""
Chroma 向量数据库实现。

基于 langchain-chroma 封装，支持：
- 文档批量写入与检索
- 按租户隔离集合
- 元数据过滤
"""

from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import get_settings
from src.core.exceptions import VectorStoreError
from src.llm.factory import LLMFactory
from src.vectorstore.base import BaseVectorStore


class ChromaVectorStore(BaseVectorStore):
    """Chroma 向量存储实现。"""

    def __init__(self) -> None:
        settings = get_settings()
        embeddings = LLMFactory(settings).create_embeddings()

        # 使用持久化目录或 HTTP 客户端
        if settings.chroma_host and settings.chroma_host != "localhost":
            import chromadb

            client = chromadb.HttpClient(
                host=settings.chroma_host, port=settings.chroma_port
            )
            self._store = Chroma(client=client, embedding_function=embeddings)
        else:
            import os

            persist_dir = os.path.abspath(settings.chroma_persist_dir)
            os.makedirs(persist_dir, exist_ok=True)
            self._store = Chroma(
                persist_directory=persist_dir,
                embedding_function=embeddings,
            )

    def _collection_name(self, base_name: str, tenant_id: str) -> str:
        """生成带租户前缀的集合名称，实现数据隔离。"""
        return f"tenant_{tenant_id}_{base_name}"

    async def add_documents(
        self,
        documents: list[Document],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> list[str]:
        """添加文档到向量库。"""
        try:
            collection = self._collection_name(collection_name, tenant_id)
            return self._store.add_documents(documents, collection_name=collection)
        except Exception as e:
            raise VectorStoreError(f"添加文档失败: {e}") from e

    async def similarity_search(
        self,
        query: str,
        collection_name: str = "default",
        tenant_id: str = "default",
        top_k: int = 5,
        **kwargs: Any,
    ) -> list[Document]:
        """相似度检索。"""
        try:
            collection = self._collection_name(collection_name, tenant_id)
            filter_dict = kwargs.pop("filter", None)
            return self._store.similarity_search(
                query, k=top_k, collection_name=collection, filter=filter_dict, **kwargs
            )
        except Exception as e:
            raise VectorStoreError(f"相似度检索失败: {e}") from e

    async def delete_by_ids(
        self, ids: list[str], collection_name: str = "default"
    ) -> bool:
        """按 ID 删除文档。"""
        try:
            self._store.delete(ids=ids, collection_name=collection_name)
            return True
        except Exception as e:
            raise VectorStoreError(f"删除文档失败: {e}") from e

    async def delete_collection(
        self, collection_name: str, tenant_id: str = "default"
    ) -> bool:
        """删除整个集合。"""
        try:
            collection = self._collection_name(collection_name, tenant_id)
            self._store.delete_collection(collection)
            return True
        except Exception as e:
            raise VectorStoreError(f"删除集合失败: {e}") from e

    async def health_check(self) -> bool:
        """检查 Chroma 连接状态。"""
        try:
            self._store._collection.count()  # type: ignore[union-attr]
            return True
        except Exception:
            return False
