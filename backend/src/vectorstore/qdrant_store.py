"""
Qdrant 向量数据库实现。

Qdrant 是高性能向量搜索引擎，特性：
- 本地运行（Windows 可执行文件 / Docker），无需额外服务编排
- 内置 Web UI（端口 6333）——向量数据可视化面板
- 支持 Cosine / Dot / Euclidean 等距离度量
- 丰富的过滤查询与分组聚合
- gRPC + REST 双协议

使用前需启动 Qdrant：

  # 方式 1：Docker Desktop（推荐）
  docker run -p 6333:6333 -p 6334:6334 -v qdrant_storage:/qdrant/storage qdrant/qdrant

  # 方式 2：Windows 独立可执行文件
  # 从 https://github.com/qdrant/qdrant/releases 下载 qdrant-x86_64-pc-windows-msvc.zip
  # 解压后运行: ./qdrant.exe

Web UI: http://localhost:6333/dashboard
REST API: http://localhost:6333
gRPC API: http://localhost:6334
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, cast

from langchain_core.documents import Document
from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

from src.core.config import get_settings
from src.core.exceptions import VectorStoreError
from src.vectorstore.base import BaseVectorStore

if TYPE_CHECKING:
    from collections.abc import Callable


class QdrantVectorStore(BaseVectorStore):
    """Qdrant 向量存储实现。

    通过 REST API 与 Qdrant 通信，支持：
    - 预计算 Embedding 直接写入（与 Chroma 接口兼容）
    - 预计算 query 向量检索
    - 按 metadata 过滤（document_id、chunk_type 等）
    - 多租户集合隔离
    """

    _DEFAULT_VECTOR_SIZE = 4096  # Qwen3-Embedding-0.6B 默认维度
    _RETRY_STATUSES = {500, 502, 503, 504}
    _MAX_RETRIES = 5
    _RETRY_BASE_DELAY = 1.0

    def __init__(self, embedding_function: Any | None = None) -> None:
        settings = get_settings()

        self._embedding_function = embedding_function
        self._client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            prefer_grpc=settings.qdrant_prefer_grpc,
            api_key=settings.qdrant_api_key.get_secret_value() or None,
            timeout=60,
            check_compatibility=False,
        )

    async def _run_sync(self, fn: Callable, *args: Any, **kwargs: Any) -> Any:
        """在线程池中执行同步 QdrantClient 调用，瞬态错误自动重试。

        Docker Desktop 的 WSL2 网络代理层在宿主机高负载时可能返回空 503。
        每次重试前关闭旧连接并重建客户端，确保使用全新的 TCP 连接。
        """
        last_exc: Exception | None = None
        for attempt in range(self._MAX_RETRIES):
            try:
                return await asyncio.to_thread(fn, *args, **kwargs)
            except UnexpectedResponse as e:
                last_exc = e
                if e.status_code not in self._RETRY_STATUSES:
                    raise
                delay = self._RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Qdrant {e.status_code} (attempt {attempt + 1}/{self._MAX_RETRIES}), "
                    f"retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                self._reconnect_client()
            except (ConnectionError, TimeoutError, OSError) as e:
                last_exc = e
                if attempt == self._MAX_RETRIES - 1:
                    raise
                delay = self._RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    f"Qdrant connection error: {e} (attempt {attempt + 1}/{self._MAX_RETRIES}), "
                    f"retrying in {delay:.1f}s..."
                )
                await asyncio.sleep(delay)
                self._reconnect_client()
        raise last_exc  # type: ignore[misc]

    def _reconnect_client(self) -> None:
        """关闭旧连接并重建 QdrantClient（强制新 TCP 连接绕过 Docker 代理缓存）。"""
        with contextlib.suppress(Exception):
            self._client.close()
        settings = get_settings()
        self._client = QdrantClient(
            host=settings.qdrant_host,
            port=settings.qdrant_port,
            prefer_grpc=settings.qdrant_prefer_grpc,
            api_key=settings.qdrant_api_key.get_secret_value() or None,
            timeout=60,
            check_compatibility=False,
        )

    def _collection_name(self, base_name: str, tenant_id: str = "default") -> str:
        return f"tenant_{tenant_id}_{base_name}"

    async def _ensure_collection(
        self, full_name: str, vector_size: int | None = None
    ) -> None:
        """确保集合存在，不存在则创建。"""
        exists = await self._run_sync(self._client.collection_exists, full_name)
        if exists:
            return
        size = vector_size or self._DEFAULT_VECTOR_SIZE
        await self._run_sync(
            self._client.create_collection,
            collection_name=full_name,
            vectors_config=VectorParams(size=size, distance=Distance.COSINE),
        )

    # ═══════════════════════════════════════════════════════════
    # BaseVectorStore 接口实现
    # ═══════════════════════════════════════════════════════════

    async def add_documents(
        self,
        documents: list[Document],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> list[str]:
        """添加文档到向量库（由 embedding_function 自动向量化）。"""
        raise NotImplementedError(
            "QdrantVectorStore 使用 add_documents_with_embeddings，"
            "不支持自动 embedding 路径"
        )

    async def add_documents_with_embeddings(
        self,
        documents: list[Document],
        embeddings: list[list[float]],
        ids: list[str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> None:
        """添加已向量化的文档，跳过内部 embedding 计算。"""
        if not documents:
            return
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            vector_size = len(embeddings[0]) if embeddings else None
            await self._ensure_collection(full_name, vector_size)

            points = [
                PointStruct(
                    id=doc_id,
                    vector=emb,
                    payload={
                        "page_content": doc.page_content,
                        **doc.metadata,
                    },
                )
                for doc, emb, doc_id in zip(documents, embeddings, ids, strict=True)
            ]
            await self._run_sync(
                self._client.upsert, collection_name=full_name, points=points
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
        """使用预计算 query 向量检索。"""
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            exists = await self._run_sync(
                self._client.collection_exists, full_name
            )
            if not exists:
                return []

            qdrant_filter = self._build_filter(filter) if filter else None

            results = await self._run_sync(
                self._client.query_points,
                collection_name=full_name,
                query=query_embedding,
                limit=top_k,
                query_filter=qdrant_filter,
                with_payload=True,
            )

            docs: list[Document] = []
            for hit in results.points:
                payload = hit.payload or {}
                content = payload.pop("page_content", "")
                payload["score"] = hit.score
                payload["distance"] = max(0.0, 1.0 - hit.score)
                docs.append(Document(
                    page_content=content,
                    metadata=payload,
                ))
            return docs
        except Exception as e:
            raise VectorStoreError(f"向量检索失败: {e}") from e

    async def get_collection_embedding_model(
        self, collection_name: str, tenant_id: str = "default"
    ) -> str | None:
        """读取 collection 中记录的 embedding 模型版本。"""
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            exists = await self._run_sync(
                self._client.collection_exists, full_name
            )
            if not exists:
                return None
            points, _ = await self._run_sync(
                self._client.scroll,
                collection_name=full_name, limit=1, with_payload=True,
            )
            if points and points[0].payload:
                return cast("str | None", points[0].payload.get("embedding_model"))
            return None
        except Exception:
            return None

    async def similarity_search(
        self,
        query: str,
        collection_name: str = "default",
        tenant_id: str = "default",
        top_k: int = 5,
        **kwargs: Any,
    ) -> list[Document]:
        """相似度检索（兼容旧调用，实际使用 similarity_search_by_vector）。"""
        raise NotImplementedError(
            "QdrantVectorStore 使用 similarity_search_by_vector，"
            "请在外部 embed 后调用"
        )

    async def delete_by_ids(
        self,
        ids: list[str],
        collection_name: str = "default",
        tenant_id: str = "default",
    ) -> bool:
        """按 ID 删除向量点。"""
        if not ids:
            return True
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            exists = await self._run_sync(
                self._client.collection_exists, full_name
            )
            if not exists:
                return True
            await self._run_sync(
                self._client.delete,
                collection_name=full_name,
                points_selector=ids,
            )
            return True
        except Exception as e:
            raise VectorStoreError(f"删除向量失败: {e}") from e

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
            exists = await self._run_sync(
                self._client.collection_exists, full_name
            )
            if not exists:
                return True
            qdrant_filter = self._build_filter(where)
            await self._run_sync(
                self._client.delete,
                collection_name=full_name,
                points_selector=FilterSelector(filter=qdrant_filter),
            )
            return True
        except Exception as e:
            raise VectorStoreError(f"按条件删除向量失败: {e}") from e

    async def delete_collection(
        self, collection_name: str, tenant_id: str = "default"
    ) -> bool:
        """删除整个集合。"""
        try:
            full_name = self._collection_name(collection_name, tenant_id)
            await self._run_sync(
                self._client.delete_collection, full_name
            )
            return True
        except Exception as e:
            raise VectorStoreError(f"删除集合失败: {e}") from e

    async def health_check(self) -> bool:
        """检查 Qdrant 连接状态。"""
        try:
            await self._run_sync(self._client.get_collections)
            return True
        except Exception:
            return False

    # ═══════════════════════════════════════════════════════════
    # 辅助方法
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _build_filter(where: dict[str, str]) -> Filter:
        """将简单的 {key: value} 字典转为 Qdrant Filter。"""
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in where.items()
        ]
        return Filter(must=conditions)  # type: ignore[arg-type]
