"""Embedding 并发安全性测试。"""

import asyncio
import threading
import time
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.services.embedding_service import EmbeddingService, get_embedding_service
from src.services.rag.embedding_strategy import GenericStrategy


@pytest.mark.unit
def test_embedding_service_has_configured_workers() -> None:
    """验证 max_workers 从配置读取。"""
    svc = EmbeddingService(model_name="test-model", device="cpu")
    assert svc._executor._max_workers >= 1


@pytest.mark.unit
def test_gpu_encode_lock_exists() -> None:
    """验证 GPU 编码锁已创建。"""
    svc = EmbeddingService(model_name="test-model", device="cpu")
    assert hasattr(svc, "_gpu_encode_lock")
    assert isinstance(svc._gpu_encode_lock, type(threading.Lock()))


@pytest.mark.unit
@patch("sentence_transformers.SentenceTransformer")
def test_gpu_encode_uses_lock(mock_st: MagicMock) -> None:
    """验证 GPU 模式下 encode 获取锁。"""
    import torch

    mock_st.return_value.get_sentence_embedding_dimension.return_value = 1024
    mock_st.return_value.encode.return_value = torch.zeros((1, 1024))

    with patch.object(torch, "set_num_threads"):
        with patch.object(torch.cuda, "is_available", return_value=True):
            svc = EmbeddingService(model_name="test-model", device="auto")
            svc._model = mock_st.return_value
            svc._initialized = True
            svc._gpu = True

            lock_acquired = False

            def _fake_encode(*args: Any, **kwargs: Any) -> Any:
                nonlocal lock_acquired
                lock_acquired = svc._gpu_encode_lock.locked()
                return torch.zeros((1, 1024))

            mock_st.return_value.encode.side_effect = _fake_encode

            async def _run() -> list[list[float]]:
                return await svc._encode(["test"], batch_size=4, extra_kwargs={})

            asyncio.run(_run())
            assert lock_acquired, "GPU encode 应持有 _gpu_encode_lock"


@pytest.mark.unit
def test_concurrent_embed_queries_no_crash() -> None:
    """验证多路并发 embed_query 不崩溃（CPU 模式）。"""
    svc = EmbeddingService(model_name="test-model", device="cpu")
    # 手动设置模拟模型
    import torch

    mock_model = MagicMock()
    # 返回 shape=[batch, dim] 的张量
    mock_model.encode.return_value = torch.zeros((1, 768))
    mock_model.get_sentence_embedding_dimension.return_value = 768
    svc._model = mock_model
    svc._initialized = True
    svc._gpu = False
    svc._strategy = GenericStrategy("test-model")

    async def _run_concurrent(n: int = 5):
        tasks = [svc.embed_query(f"查询 {i}") for i in range(n)]
        start = time.perf_counter()
        results = await asyncio.gather(*tasks)
        elapsed = time.perf_counter() - start
        return results, elapsed

    results, elapsed = asyncio.run(_run_concurrent(5))
    assert len(results) == 5
    # 并发 5 请求应在 2s 内完成（mock 场景下极快）
    assert elapsed < 2.0, f"并发耗时 {elapsed:.2f}s 过长"

    # 验证 mock 被调用了 5 次（每个请求各一次 encode）
    assert mock_model.encode.call_count == 5


@pytest.mark.unit
def test_get_embedding_service_singleton() -> None:
    """验证 get_embedding_service 返回单例。"""
    svc1 = get_embedding_service("Qwen/Qwen3-Embedding-0.6B")
    svc2 = get_embedding_service("Qwen/Qwen3-Embedding-0.6B")
    assert svc1 is svc2
