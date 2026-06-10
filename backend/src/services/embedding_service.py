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
import time
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
        concurrency = max(1, self._settings.kb_embedding_concurrency)
        self._executor = ThreadPoolExecutor(max_workers=concurrency)
        self._initialized = False
        self._gpu = False
        self._init_lock = threading.Lock()
        self._gpu_encode_lock = threading.Lock()  # GPU 推理互斥——防止多线程同时 encode 导致 OOM

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
                import torch

                torch.set_num_threads(4)
                from sentence_transformers import SentenceTransformer

                # 设备选择：优先 GPU，显式 bfloat16 节省一半显存
                if self._device == "cpu":
                    self._gpu = False
                elif torch.cuda.is_available():
                    self._gpu = True
                else:
                    self._gpu = False

                if self._gpu:
                    logger.info(
                        f"加载 Embedding 模型: {self._model_name} (GPU, bfloat16)"
                    )
                    self._model = SentenceTransformer(
                        self._model_name,
                        device="cuda",
                        trust_remote_code=True,
                        model_kwargs={"torch_dtype": torch.bfloat16},
                    )
                    torch.cuda.empty_cache()
                else:
                    logger.info(
                        f"加载 Embedding 模型: {self._model_name} (CPU)"
                    )
                    self._model = SentenceTransformer(
                        self._model_name,
                        device="cpu",
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
        batch_size: int = 16,
        strategy: EmbeddingStrategy | None = None,
    ) -> list[list[float]]:
        """批量文档向量化——走 document 侧格式化，优先从 Redis 缓存读取。

        支持攒批：当 kb_embedding_batch_wait_ms > 0 时，合并短时间窗口内
        的多次调用为一次 GPU 批处理，提升 GPU 利用率。
        """
        active_strategy = strategy or self._strategy
        formatted = [active_strategy.format_document(t) for t in texts]

        # 攒批模式：通过异步队列合并并发请求
        batch_wait = self._settings.kb_embedding_batch_wait_ms
        if batch_wait > 0 and len(formatted) <= 4:
            return await self._embed_with_batching(
                formatted, batch_size, active_strategy, batch_wait
            )

        # 检查 Redis 缓存
        if self._settings.kb_embedding_cache_enabled and len(formatted) > 0:
            try:
                from src.services.redis_service import RedisService
                redis = await RedisService.get_instance()
                if redis.available:
                    cached, missing = await redis.get_embeddings_batch(
                        self._model_name, formatted
                    )
                    if not missing:
                        # 全部命中缓存
                        return [cached[i] for i in range(len(formatted))]
                    if cached:
                        # 部分命中——仅计算缺失的
                        missing_texts = [formatted[i] for i in sorted(missing)]
                        extra = active_strategy.encode_kwargs_for_document()
                        missing_vectors = await self._encode(missing_texts, batch_size, extra)
                        # 写入缺失的缓存
                        await redis.set_embeddings_batch(
                            self._model_name, missing_texts, missing_vectors,
                            ttl=self._settings.kb_embedding_cache_ttl,
                        )
                        # 组装结果
                        result = []
                        miss_iter = iter(missing_vectors)
                        for i in range(len(formatted)):
                            if i in cached:
                                result.append(cached[i])
                            else:
                                result.append(next(miss_iter))
                        return result
            except Exception as e:
                logger.debug("Redis embedding cache check failed: {}", e)

        extra = active_strategy.encode_kwargs_for_document()
        vectors = await self._encode(formatted, batch_size, extra)

        # 写入 Redis 缓存
        if self._settings.kb_embedding_cache_enabled and vectors:
            try:
                from src.services.redis_service import RedisService
                redis = await RedisService.get_instance()
                if redis.available:
                    await redis.set_embeddings_batch(
                        self._model_name, formatted, vectors,
                        ttl=self._settings.kb_embedding_cache_ttl,
                    )
            except Exception as e:
                logger.debug("Redis embedding cache write failed: {}", e)

        return vectors

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
        import torch

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._lazy_init)

        # GPU 上 batch 太大会 OOM（32条×768tokens 的 attention 矩阵 ~数 GB）
        if self._gpu and batch_size > 4:
            batch_size = 4

        def _run() -> list[list[float]]:
            try:
                if self._gpu:
                    # GPU 推理互斥：多线程 CPU 预处理可并行，但 encode 调用必须串行
                    with self._gpu_encode_lock:
                        embeddings = self._model.encode(
                            texts,
                            batch_size=batch_size,
                            show_progress_bar=False,
                            normalize_embeddings=True,
                            **extra_kwargs,
                        )
                else:
                    embeddings = self._model.encode(
                        texts,
                        batch_size=batch_size,
                        show_progress_bar=False,
                        normalize_embeddings=True,
                        **extra_kwargs,
                    )
                return embeddings.tolist()
            except torch.cuda.OutOfMemoryError:
                # GPU OOM 时回退到 CPU
                logger.warning("GPU OOM，回退 CPU 编码")
                self._model.to("cpu")
                import gc
                gc.collect()
                torch.cuda.empty_cache()
                embeddings = self._model.encode(
                    texts,
                    batch_size=8,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                    **extra_kwargs,
                )
                result = embeddings.tolist()
                self._model.to("cuda")
                torch.cuda.empty_cache()
                return result
            finally:
                if self._gpu:
                    torch.cuda.empty_cache()

        return await loop.run_in_executor(self._executor, _run)

    # ── 攒批 ────────────────────────────────────────────────

    async def _embed_with_batching(
        self,
        texts: list[str],
        batch_size: int,
        strategy: EmbeddingStrategy,
        wait_ms: int,
    ) -> list[list[float]]:
        """通过攒批器合并短窗口内的并发 embedding 请求。

        工作方式：
        1. 注册当前请求到模块级攒批器
        2. 等待窗口后，攒批器合并所有请求为一次 encode 调用
        3. 结果按原始顺序分发给各调用方
        """
        batch_key = self._model_name  # 按模型名隔离攒批
        return await _get_embedding_batcher().submit(
            batch_key, texts, batch_size, strategy, self, wait_ms,
        )

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


# ---- 攒批器 ----

class EmbeddingBatcher:
    """异步攒批器：合并短时间窗口内的 embedding 请求为一次批量编码。

    使用 asyncio.Event 协调：第一个请求触发等待窗口，窗口关闭后
    批量编码所有收集到的文本，结果按原始位置分发给各调用方。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # batch_key → (futures, texts, activation_time)
        self._pending: dict[
            str,
            tuple[list[asyncio.Future], list[str], float],
        ] = {}
        # batch_key → asyncio.Task (batch processing task)
        self._tasks: dict[str, asyncio.Task] = {}

    async def submit(
        self,
        batch_key: str,
        texts: list[str],
        batch_size: int,
        strategy: EmbeddingStrategy,
        service: Any,
        wait_ms: int,
    ) -> list[list[float]]:
        """提交 embedding 请求，可能在窗口内与其他请求合并。"""
        import asyncio as _asyncio

        loop = _asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()

        with self._lock:
            if batch_key not in self._pending:
                # 第一个请求：创建新的攒批窗口
                self._pending[batch_key] = ([], [], time.time())

                # 启动延迟任务
                task = _asyncio.ensure_future(
                    self._drain_after(batch_key, batch_size, strategy, service, wait_ms)
                )
                self._tasks[batch_key] = task

            futures, all_texts, _ = self._pending[batch_key]
            start_idx = len(all_texts)  # 记录当前文本的起始位置
            futures.append(fut)
            all_texts.extend(texts)

        result = await fut
        # 返回属于本次调用的结果切片
        return result[start_idx : start_idx + len(texts)]

    async def _drain_after(
        self,
        batch_key: str,
        batch_size: int,
        strategy: EmbeddingStrategy,
        service: Any,
        wait_ms: int,
    ) -> None:
        """等待窗口关闭后批量编码。"""
        import asyncio as _asyncio

        wait_sec = wait_ms / 1000.0
        max_batch = get_settings().kb_embedding_batch_max

        try:
            await _asyncio.sleep(wait_sec)

            with self._lock:
                if batch_key not in self._pending:
                    return
                futures, all_texts, _ = self._pending.pop(batch_key)
                self._tasks.pop(batch_key, None)

            if not all_texts:
                return

            # 截断到最大攒批量
            if len(all_texts) > max_batch:
                logger.debug(
                    f"Embedding 攒批截断: {len(all_texts)} → {max_batch}"
                )
                all_texts = all_texts[:max_batch]

            # 批量编码
            extra = strategy.encode_kwargs_for_document()
            vectors = await service._encode(all_texts, batch_size, extra)  # noqa: SLF001

            # 分发给各调用方
            for _i, f in enumerate(futures):
                if not f.done():
                    f.set_result(vectors)

        except Exception as e:
            logger.warning(f"Embedding 攒批失败: {e}")
            # 失败时逐个设置为异常
            with self._lock:
                popped = self._pending.pop(batch_key, (None, None, None))
                self._tasks.pop(batch_key, None)
            if popped[0]:
                for f in popped[0]:
                    if not f.done():
                        f.set_exception(e)


_embedding_batcher: EmbeddingBatcher | None = None
_batcher_lock = threading.Lock()


def _get_embedding_batcher() -> EmbeddingBatcher:
    global _embedding_batcher
    if _embedding_batcher is None:
        with _batcher_lock:
            if _embedding_batcher is None:
                _embedding_batcher = EmbeddingBatcher()
    return _embedding_batcher


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
