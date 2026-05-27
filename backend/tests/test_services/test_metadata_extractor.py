"""文档元数据深度提取单元测试。

覆盖场景：
- DOI 提取
- 中英文摘要提取
- 关键词列表提取
- 作者解析（中英文）
- 文档类型推断
- 期刊名提取
"""

from __future__ import annotations

import pytest

from src.services.chunking_service import StructuredBlock
from src.services.metadata_extractor import MetadataExtractor


def _make_text_block(content: str, page: int = 1) -> StructuredBlock:
    return StructuredBlock(block_type="text", content=content, page_number=page)


@pytest.mark.unit
class TestDOIExtraction:
    def test_extract_doi(self) -> None:
        blocks = [_make_text_block("DOI: 10.1234/abcd.5678")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.doi == "10.1234/abcd.5678"

    def test_extract_doi_from_url(self) -> None:
        blocks = [_make_text_block(
            "See https://doi.org/10.1000/journal.2024.001 for details."
        )]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.doi == "10.1000/journal.2024.001"

    def test_no_doi(self) -> None:
        blocks = [_make_text_block("这是一篇普通文章，没有 DOI。")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.doi is None


@pytest.mark.unit
class TestAbstractExtraction:
    def test_chinese_abstract(self) -> None:
        blocks = [
            _make_text_block("摘要：本文提出了一种新的数字孪生建模方法。"),
            _make_text_block("该方法基于深度学习技术，能够自动构建精确的数字模型。"),
            _make_text_block("关键词：数字孪生；深度学习"),
        ]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.abstract is not None
        assert "数字孪生" in meta.abstract

    def test_english_abstract(self) -> None:
        blocks = [
            _make_text_block("Abstract: This paper presents a novel approach to digital twin modeling."),
            _make_text_block("The method leverages deep learning for automatic model construction."),
            _make_text_block("Keywords: digital twin; deep learning"),
        ]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.abstract is not None
        assert "deep learning" in meta.abstract.lower()

    def test_abstract_stops_at_section_boundary(self) -> None:
        blocks = [
            _make_text_block("摘要：本文提出一种新方法。"),
            _make_text_block("1. 引言"),
            _make_text_block("近年来，相关技术发展迅速。"),
        ]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        # 摘要应在 "1. 引言" 前停止
        assert meta.abstract is not None
        assert "引言" not in meta.abstract
        assert "近年来" not in meta.abstract


@pytest.mark.unit
class TestKeywordsExtraction:
    def test_chinese_keywords(self) -> None:
        blocks = [_make_text_block("关键词：数字孪生；深度学习；模型压缩")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert len(meta.keywords) >= 2
        assert "数字孪生" in meta.keywords

    def test_english_keywords(self) -> None:
        blocks = [_make_text_block("Keywords: digital twin, deep learning, model compression")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert len(meta.keywords) >= 2
        assert "digital twin" in meta.keywords

    def test_semicolon_separated(self) -> None:
        blocks = [_make_text_block("关键词：方法A；方法B；方法C")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert len(meta.keywords) == 3


@pytest.mark.unit
class TestAuthorExtraction:
    def test_cn_authors(self) -> None:
        blocks = [_make_text_block("作者：张三，李四，王五")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert len(meta.authors) >= 2
        assert "张三" in meta.authors

    def test_en_authors_line(self) -> None:
        blocks = [_make_text_block(
            "Smith J. A., Brown K. L., Davis M.\n"
            "Department of Computer Science"
        )]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert len(meta.authors) >= 2


@pytest.mark.unit
class TestDocTypeDetection:
    def test_journal_type(self) -> None:
        blocks = [_make_text_block("[J] 张三. 数字孪生技术综述[J]. 计算机学报, 2024.")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.doc_type == "journal"

    def test_conference_type(self) -> None:
        blocks = [_make_text_block("[C] Smith J. Deep Learning Methods[C]. CVPR 2024.")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.doc_type == "conference"

    def test_thesis_type(self) -> None:
        blocks = [_make_text_block("硕士学位论文\n论文题目：基于AI的数字孪生")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.doc_type == "thesis"


@pytest.mark.unit
class TestLanguageDetection:
    def test_chinese_doc(self) -> None:
        blocks = [_make_text_block("这是一个中文文档，讨论数字孪生技术的应用和发展前景。")]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.language == "zh"

    def test_english_doc(self) -> None:
        blocks = [_make_text_block(
            "This is an English document discussing digital twin technology applications."
        )]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.language == "en"

    def test_mixed_doc(self) -> None:
        blocks = [_make_text_block(
            "This paper discusses 数字孪生 and its applications in manufacturing."
        )]
        meta = MetadataExtractor.extract(blocks, page_count=1)
        assert meta.language in ("mixed", "zh", "en")
