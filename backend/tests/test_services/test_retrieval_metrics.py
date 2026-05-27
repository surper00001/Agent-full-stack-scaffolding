"""检索 Metrics 测试。"""

import io

import pytest
from loguru import logger

from src.services.rag.retrieval_pipeline import RetrievalPipeline


@pytest.fixture(autouse=True)
def _capture_loguru(pytestconfig: pytest.Config) -> None:
    """确保 loguru 输出到 pytest capture 的 stderr sink（默认已配置）。"""
    _ = pytestconfig


def _make_pipeline(enabled: bool) -> RetrievalPipeline:
    from unittest.mock import MagicMock

    settings = MagicMock()
    settings.kb_retrieval_metrics_enabled = enabled
    pipeline = object.__new__(RetrievalPipeline)
    pipeline._settings = settings
    return pipeline


@pytest.mark.unit
def test_log_metrics_runs_without_crash() -> None:
    """验证 _log_metrics 不会抛出异常（所有字段正常）。"""
    pipeline = _make_pipeline(enabled=True)
    timings = {"embed": 15.2, "retrieval": 8.7, "rerank": 45.1, "dedup": 2.3, "total": 75.0}
    # 不应该抛出异常
    pipeline._log_metrics("测试查询", 5, 20, True, timings)


@pytest.mark.unit
def test_log_metrics_skipped_when_disabled() -> None:
    """禁用时不产生任何日志（追加 loguru sink 捕获验证）。"""
    sink = io.StringIO()
    handler_id = logger.add(sink, level="INFO", format="{message}")

    try:
        pipeline = _make_pipeline(enabled=False)
        timings = {"embed": 15.2, "total": 75.0}
        pipeline._log_metrics("测试", 5, 1, True, timings)
        captured = sink.getvalue()
        assert "[检索 Metrics]" not in captured
    finally:
        logger.remove(handler_id)


@pytest.mark.unit
def test_log_metrics_enabled_outputs_expected_fields() -> None:
    """启用时输出包含所有计时字段。"""
    sink = io.StringIO()
    handler_id = logger.add(sink, level="INFO", format="{message}")

    try:
        pipeline = _make_pipeline(enabled=True)
        timings = {"embed": 15.2, "retrieval": 8.7, "rerank": 45.1, "dedup": 2.3, "total": 75.0}
        pipeline._log_metrics("测试查询", 5, 20, True, timings)
        captured = sink.getvalue()
        assert "[检索 Metrics]" in captured
        assert "embed=15.2ms" in captured
        assert "retrieval=8.7ms" in captured
        assert "rerank=45.1ms" in captured
        assert "dedup=2.3ms" in captured
        assert "total=75.0ms" in captured
        assert "total_found=20" in captured
        assert "reranked=True" in captured
    finally:
        logger.remove(handler_id)


@pytest.mark.unit
def test_log_metrics_partial_timings_no_crash() -> None:
    """部分步骤缺失时不影响输出。"""
    sink = io.StringIO()
    handler_id = logger.add(sink, level="INFO", format="{message}")

    try:
        pipeline = _make_pipeline(enabled=True)
        timings = {"total": 42.0}
        pipeline._log_metrics("查询", 3, 0, False, timings)
        captured = sink.getvalue()
        assert "total=42.0ms" in captured
        assert "reranked=False" in captured
        # 未包含的字段不应出现
        assert "embed" not in captured
    finally:
        logger.remove(handler_id)
