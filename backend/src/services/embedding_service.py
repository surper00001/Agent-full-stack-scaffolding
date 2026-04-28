"""
Embedding 服务。

封装 sentence-transformers 模型，提供文本向量化能力。
支持按模型名缓存多实例，并通过 EmbeddingStrategy 区分 query/document 编码。

模块级单例（默认模型）+ 按模型名缓存（KB 级绑定）。
首次加载会阻塞事件循环约 60-90 秒，后续调用均为非阻塞。
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from src.core.config import get_settings
from src.services.rag.embedding_strategy import EmbeddingStrategy, get_embedding_strategy


class EmbeddingService:
    """文本向量化服务——按模型名隔离实例。"""

    def __init__(
        self,
        model_name: str | None = None,
        device: str = "auto",
        strategy: EmbeddingStrategy | None = None,
    ) -> None:
        self._settings = get_settings()
        self._model_name = model_name or self._settings.kb_embedding_model
        self._device = device or self._settings.kb_embedding_device
        self._strategy = strategy or get_embedding_strategy(self._model_name)
        self._model: Any = None
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._initialized = False
        self._init_lock = threading.Lock()

    def _lazy_init(self) -> None:
        """同步初始化模型（首次调用阻塞，之后立即返回）。"""
        if self._initialized:
            return
        with self._init_lock:
            if self._initialized:
                return
            try:
                if self._settings.hf_endpoint:
                    import os

                    os.environ.setdefault("HF_ENDPOINT", self._settings.hf_endpoint)
                from sentence_transformers import SentenceTransformer

                logger.info(f"加载 Embedding 模型: {self._model_name} (device={self._device})")
                self._model = SentenceTransformer(
                    self._model_name,
                    device=self._device if self._device != "auto" else None,
                    trust_remote_code=True,
                )
                self._initialized = True
                dim = (
                    self._model.get_embedding_dimension()
                    if hasattr(self._model, "get_embedding_dimension")
                    else self._model.get_sentence_embedding_dimension()
                )
                logger.info(f"Embedding 模型加载完成，维度: {dim}")
            except Exception as e:
                logger.error(f"加载 Embedding 模型失败: {e}")
                raise

    async def embed_documents(
        self,
        texts: list[str],
        batch_size: int = 32,
        strategy: EmbeddingStrategy | None = None,
    ) -> list[list[float]]:
        """批量文档向量化——走 document 侧格式化。"""
        active_strategy = strategy or self._strategy
        formatted = [active_strategy.format_document(t) for t in texts]
        extra = active_strategy.encode_kwargs_for_document()
        return await self._encode(formatted, batch_size, extra)

    async def embed_texts(
        self,
        texts: list[str],
        batch_size: int = 32,
        strategy: EmbeddingStrategy | None = None,
    ) -> list[list[float]]:
        """批量文本向量化（兼容旧接口，等同 embed_documents）。"""
        return await self.embed_documents(texts, batch_size, strategy)

    async def embed_query(
        self,
        query: str,
        strategy: EmbeddingStrategy | None = None,
    ) -> list[float]:
        """单条 query 向量化——走 query 侧格式化。"""
        active_strategy = strategy or self._strategy
        formatted = active_strategy.format_query(query)
        extra = active_strategy.encode_kwargs_for_query()
        results = await self._encode([formatted], 32, extra)
        return results[0]

    async def _encode(
        self,
        texts: list[str],
        batch_size: int,
        extra_kwargs: dict[str, Any],
    ) -> list[list[float]]:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._lazy_init)

        def _run() -> list[list[float]]:
            embeddings = self._model.encode(
                texts,
                batch_size=batch_size,
                show_progress_bar=False,
                normalize_embeddings=True,
                **extra_kwargs,
            )
            return embeddings.tolist()

        return await loop.run_in_executor(self._executor, _run)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def strategy(self) -> EmbeddingStrategy:
        return self._strategy

    @property
    def is_ready(self) -> bool:
        return self._initialized

    def to_langchain(self) -> LangchainEmbeddingAdapter:
        """转换为 langchain 兼容的 Embeddings 接口。"""
        return LangchainEmbeddingAdapter(self)


# ---- 按模型名缓存 ----

_embedding_services: dict[str, EmbeddingService] = {}
_embedding_lock = threading.Lock()


def get_embedding_service(model_name: str | None = None) -> EmbeddingService:
    """获取 EmbeddingService 实例（同模型名共享）。"""
    settings = get_settings()
    resolved = model_name or settings.kb_embedding_model
    if resolved not in _embedding_services:
        with _embedding_lock:
            if resolved not in _embedding_services:
                _embedding_services[resolved] = EmbeddingService(resolved)
    return _embedding_services[resolved]


# ---- Langchain 适配器 ----

class LangchainEmbeddingAdapter:
    """将 EmbeddingService 包装为 langchain Embeddings 接口。"""

    def __init__(self, service: EmbeddingService) -> None:
        self._svc = service
        self._executor = service._executor

    def __call__(self, input: list[str]) -> list[list[float]]:  # noqa: A002
        return self.embed_documents(input)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        formatted = [self._svc.strategy.format_document(t) for t in texts]
        extra = self._svc.strategy.encode_kwargs_for_document()
        return self._sync_encode(formatted, extra)

    def embed_query(self, text: str) -> list[float]:
        formatted = self._svc.strategy.format_query(text)
        extra = self._svc.strategy.encode_kwargs_for_query()
        return self._sync_encode([formatted], extra)[0]

    def name(self) -> str:
        return self._svc.model_name

    def _sync_encode(self, texts: list[str], extra_kwargs: dict[str, Any]) -> list[list[float]]:
        self._svc._lazy_init()
        embeddings = self._svc._model.encode(
            texts,
            batch_size=32,
            show_progress_bar=False,
            normalize_embeddings=True,
            **extra_kwargs,
        )
        return embeddings.tolist()


# 向后兼容别名
LangchainBGEAdapter = LangchainEmbeddingAdapter
