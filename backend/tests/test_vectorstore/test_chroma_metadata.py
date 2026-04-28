"""Chroma metadata 清洗单元测试。"""

import pytest

from src.vectorstore.chroma_store import _sanitize_chroma_metadata


@pytest.mark.unit
def test_sanitize_removes_empty_bbox_list() -> None:
    meta = {"chunk_id": "c1", "bbox": [], "page_start": 1}
    cleaned = _sanitize_chroma_metadata(meta)
    assert "bbox" not in cleaned
    assert cleaned["chunk_id"] == "c1"
    assert cleaned["page_start"] == 1


@pytest.mark.unit
def test_sanitize_keeps_non_empty_bbox() -> None:
    bbox = [10.0, 20.0, 100.0, 200.0]
    meta = {"chunk_id": "c1", "bbox": bbox}
    cleaned = _sanitize_chroma_metadata(meta)
    assert cleaned["bbox"] == bbox


@pytest.mark.unit
def test_sanitize_drops_none_values() -> None:
    meta = {"chunk_id": "c1", "ocr_error": None}
    cleaned = _sanitize_chroma_metadata(meta)
    assert "ocr_error" not in cleaned
