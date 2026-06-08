"""
Chroma 向量数据库实现。

基于 langchain-chroma 封装，支持：
- 文档批量写入与检索
- 按租户隔离集合
- 元数据过滤
- 预计算 Embedding 直接写入
- 预计算 query 向量检索（避免 langchain 二次 embed 路径不一致）
"""

from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from src.core.config import get_settings
from src.core.exceptions import VectorStoreError
from src.vectorstore.base import BaseVectorStore


class _DummyEmbedding:
    """占位 embedding —— 预计算模式下不会被调用。"""

    @staticmethod
    def name() -> str:
        return "dummy"

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return [[0.0] for _ in input]


_dummy_embedding = _DummyEmbedding()


def _sanitize_chroma_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """清洗 metadata 以符合 Chroma 约束。

    Chroma 不接受 None；list 类型值必须非空（空列表会触发 add 失败）。
    """
    cleaned: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (list, dict)) and len(value) == 0:
            continue
        cleaned[key] = value
    return cleaned


class ChromaVectorStore(BaseVectorStore):
    """Chroma 向量存储实现。"""

    def __init__(self, embedding_function: Any | None = None) -> None:
        settings = get_settings()

        if settings.chroma_host and settings.chroma_host != "localhost":
            import chromadb

            client = chromadb.HttpClient(
                host=settings.chroma_host, port=settings.chroma_port
            )
            self._store = Chroma(
                client=client, embedding_function=embedding_function or _dummy_embedding
            )
        else:
            import os

            persist_dir = os.path.abspath(settings.chroma_persist_dir)
            os.makedirs(persist_dir, exist_ok=True)
            self._store = Chroma(
                persist_directory=persist_dir,
                embedding_function=embedding_function or _dummy_embedding,
            )

        self._persist_dir = os.path.abspath(settings.chroma_persist_dir)

    def _collection_name(self, base_name: str, tenant_id: str = "default") -> str:
        return f"tenant_{tenant_id}_{base_name}"

    def _get_client(self) -> Any:
        return self._store._client  # type: ignore[attr-defined]

    def _get_collection(self, full_collection_name: str) -> Any:
        """获取 chromadb Collection 对象。"""
        client = self._get_client()
        return client.get_or_create_collection(
            name=full_collection_name,
            embedding_function=self._store._embedding_function,  # type: ignore[attr-defined]
        )

    def _get_collection_store(self, full_collection_name: str) -> Chroma:
        """获取绑定到指定 collection 的 Chroma 实例。"""
        embedding_function = self._store._embedding_function  # type: ignore[attr-defined]
        client = getattr(self._store, "_client", None)
        if client is not None:
            return Chroma(
                client=client,
                collection_name=full_collection_name,
                embedding_function=embedding_function,
            )
        return Chroma(
            persist_directory=self._persist_dir,
            collection_name=full_collection_name,
            embedding_function=embedding_function,
        )

    async def add_documents(
        self,
        documents: list[Document],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> list[str]:
        """添加文档到向量库（由 embedding_function 自动向量化）。"""
        try:
            collection = self._collection_name(collection_name, tenant_id)
            return self._get_collection_store(collection).add_documents(documents)
        except Exception as e:
            raise VectorStoreError(f"添加文档失败: {e}") from e

    async def add_documents_with_embeddings(
        self,
        documents: list[Document],
        embeddings: list[list[float]],
        ids: list[str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> None:
        """添加已向量化的文档，跳过内部 embedding 计算。"""
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            coll = self._get_collection(full_name)
            coll.add(
                embeddings=embeddings,
                documents=[doc.page_content for doc in documents],
                metadatas=[
                    _sanitize_chroma_metadata(doc.metadata) for doc in documents
                ],
                ids=ids,
            )
        except Exception as e:
            raise VectorStoreError(f"添加 embeddings 失败: {e}") from e

    async def similarity_search_by_vector(
        self,
        query_embedding: list[float],
        collection_name: str = "default",
        tenant_id: str = "default",
        top_k: int = 5,
        filter: dict[str, Any] | None = None,  # noqa: A002
    ) -> list[Document]:
        """使用预计算 query 向量检索——与索引路径保持一致。"""
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            coll = self._get_collection(full_name)
            if coll.count() == 0:
                return []

            result = coll.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, coll.count()),
                where=filter,
                include=["documents", "metadatas", "distances"],
            )

            docs: list[Document] = []
            if not result["ids"] or not result["ids"][0]:
                return docs

            for i, _doc_id in enumerate(result["ids"][0]):
                content = result["documents"][0][i] if result["documents"] else ""
                metadata = result["metadatas"][0][i] if result["metadatas"] else {}
                distance = result["distances"][0][i] if result["distances"] else 0.0
                doc = Document(page_content=content or "", metadata=metadata or {})
                # Chroma 返回距离，转为相似度分数（cosine distance → similarity）
                distance = float(distance)
                doc.metadata["distance"] = distance
                doc.metadata["score"] = max(0.0, 1.0 - distance)
                docs.append(doc)
            return docs
        except Exception as e:
            raise VectorStoreError(f"向量检索失败: {e}") from e

    async def get_collection_embedding_model(
        self, collection_name: str, tenant_id: str = "default"
    ) -> str | None:
        """读取 collection 中记录的 embedding 模型版本（用于一致性校验）。"""
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            coll = self._get_collection(full_name)
            if coll.count() == 0:
                return None
            peek = coll.get(limit=1, include=["metadatas"])
            if peek["metadatas"]:
                return peek["metadatas"][0].get("embedding_model")
            return None
        except Exception as e:
            logger.debug(f"获取 Embedding 模型名失败 [collection={collection_name}]: {e}")
            return None

    async def similarity_search(
        self,
        query: str,
        collection_name: str = "default",
        tenant_id: str = "default",
        top_k: int = 5,
        **kwargs: Any,
    ) -> list[Document]:
        """相似度检索（langchain 路径，兼容旧调用）。"""
        import time as _t
        _start = _t.perf_counter()
        try:
            collection = self._collection_name(collection_name, tenant_id)
            filter_dict = kwargs.pop("filter", None)
            result = self._get_collection_store(collection).similarity_search(
                query, k=top_k, filter=filter_dict, **kwargs
            )
            from src.monitoring.metrics import VECTOR_DB_QUERY_LATENCY
            VECTOR_DB_QUERY_LATENCY.labels(operation="search", store_type="chroma").observe(
                _t.perf_counter() - _start
            )
            return result
        except Exception as e:
            raise VectorStoreError(f"相似度检索失败: {e}") from e

    async def delete_by_ids(
        self,
        ids: list[str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> bool:
        """按 ID 删除文档。"""
        if not ids:
            return True
        try:
            collection = self._collection_name(collection_name, tenant_id)
            self._get_collection_store(collection).delete(ids=ids)
            return True
        except Exception as e:
            raise VectorStoreError(f"删除文档失败: {e}") from e

    async def delete_by_filter(
        self,
        where: dict[str, str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> bool:
        """按 metadata 条件删除向量（兜底清理孤儿向量）。"""
        if not where:
            return True
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            self._get_collection(full_name).delete(where=where)
            return True
        except Exception as e:
            raise VectorStoreError(f"按条件删除向量失败: {e}") from e

    async def delete_collection(
        self, collection_name: str, tenant_id: str = "default"
    ) -> bool:
        """删除整个集合。"""
        try:
            collection = self._collection_name(collection_name, tenant_id)
            self._get_collection_store(collection).delete_collection()
            return True
        except Exception as e:
            raise VectorStoreError(f"删除集合失败: {e}") from e

    async def health_check(self) -> bool:
        """检查 Chroma 连接状态。"""
        try:
            self._store._collection.count()  # type: ignore[union-attr]
            return True
        except Exception as e:
            logger.debug(f"ChromaDB 健康检查失败: {e}")
            return False
