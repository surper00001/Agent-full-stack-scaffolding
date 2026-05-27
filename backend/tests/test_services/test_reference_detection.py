"""
参考文献识别测试 —— 验证 _group_by_section 和 chunk_blocks 能正确检测参考文献。

BUG 根因：
_grou_by_section 中 section_title 优先级高于 layout_tag，
当参考文献块继承 section_title="参考文献" 时，block_key 为 "参考文献" 而非 "__REFERENCES__"，
chunk_blocks 只识别 "__REFERENCES__"，导致参考文献漏识别。
"""

from __future__ import annotations

import pytest
from src.services.chunking.data_models import ChunkResult, StructuredBlock
from src.services.chunking_service import ChunkingService
from src.services.reference_extractor import ReferenceExtractor


def _make_block(
    content: str,
    block_type: str = "text",
    page_number: int = 1,
    section_title: str | None = None,
    section_path: str | None = None,
    layout_tag: str | None = None,
) -> StructuredBlock:
    return StructuredBlock(
        block_type=block_type,
        content=content,
        page_number=page_number,
        section_title=section_title,
        section_path=section_path,
        layout_tag=layout_tag,
    )


def _make_chunker(
    child_size: int = 768, child_overlap: int = 128, doc_category: str = "general"
) -> ChunkingService:
    svc = ChunkingService(
        child_chunk_size=child_size,
        child_chunk_overlap=child_overlap,
        parent_chunk_size=2000,
        parent_chunk_overlap=200,
    )
    svc.doc_category = doc_category
    svc._active_separators = svc._CATEGORY_SEPARATORS.get(
        doc_category, svc._SEPARATORS_SEMANTIC
    )
    return svc


class TestGroupBySectionReference:
    """_group_by_section 参考文献归一化测试。"""

    def test_heading_with_reference_title_normalizes(self):
        """参考文献标题块 → 归一化为 __REFERENCES__。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="参考文献",
                layout_tag="heading",
                section_title=None,
            ),
        ]
        groups = svc._group_by_section(blocks)
        assert len(groups) == 1
        assert groups[0][0] == "__REFERENCES__", (
            f"期望 key='__REFERENCES__'，实际 '{groups[0][0]}'"
        )

    def test_heading_with_english_ref_title_normalizes(self):
        """英文 References 标题 → 归一化为 __REFERENCES__。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="References",
                layout_tag="heading",
                section_title=None,
            ),
        ]
        groups = svc._group_by_section(blocks)
        assert groups[0][0] == "__REFERENCES__"

    def test_section_title_reference_normalizes(self):
        """参考文献条目（继承 section_title='参考文献'）→ 归一化。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="参考文献",
                layout_tag="heading",
                section_title=None,
            ),
            _make_block(
                content="[1] 张三, 李四. 人工智能在林业中的应用[J]. 林业科学, 2023.",
                layout_tag="reference",
                section_title="参考文献",  # 继承自标题
            ),
        ]
        groups = svc._group_by_section(blocks)
        # 两个块应归入同一组，key 为 __REFERENCES__
        assert len(groups) == 1
        assert groups[0][0] == "__REFERENCES__", (
            f"期望 key='__REFERENCES__'，实际 '{groups[0][0]}'"
        )
        assert len(groups[0][1]) == 2, f"期望 2 个块，实际 {len(groups[0][1])}"

    def test_reference_layout_tag_without_section_title(self):
        """仅 layout_tag='reference' 无 section_title → __REFERENCES__。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="[1] Author A. Title A. Journal A, 2020.",
                layout_tag="reference",
                section_title=None,
            ),
            _make_block(
                content="[2] Author B. Title B. Journal B, 2021.",
                layout_tag="reference",
                section_title=None,
            ),
        ]
        groups = svc._group_by_section(blocks)
        assert len(groups) == 1
        assert groups[0][0] == "__REFERENCES__"

    def test_normal_section_title_not_affected(self):
        """非参考文献的 section_title 不受影响。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="系统架构",
                layout_tag="heading",
                section_title=None,
            ),
            _make_block(
                content="系统采用分层架构设计...",
                layout_tag="body",
                section_title="系统架构",
            ),
        ]
        groups = svc._group_by_section(blocks)
        assert len(groups) == 1
        assert groups[0][0] == "系统架构", (
            f"普通章节标题不应被归一化，实际 '{groups[0][0]}'"
        )


class TestChunkBlocksReference:
    """chunk_blocks 参考文献处理测试。"""

    def test_extracts_entries_from_numbered_refs(self):
        """chunk_blocks 应从带编号的参考文献中提取条目。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="参考文献",
                layout_tag="heading",
                section_title=None,
            ),
            _make_block(
                content=(
                    "[1] 张三, 李四. 数字孪生系统架构研究[J]. 计算机学报, 2023, 46(3): 500-520.\n"
                    "[2] Smith J, Doe R. Forest management optimization[C]. "
                    "Proc of IEEE Conf, 2022: 100-110.\n"
                    "[3] 王五. 基于深度学习的图像识别方法[D]. 清华大学, 2024."
                ),
                layout_tag="reference",
                section_title="参考文献",
                page_number=10,
            ),
        ]

        results = svc.chunk_blocks(blocks)
        ref_chunks = [c for c in results if c.chunk_type == "reference"]

        # 应提取出 3 条参考文献
        assert len(ref_chunks) == 3, (
            f"期望 3 条参考文献，实际 {len(ref_chunks)} 条"
        )
        # 每条应有 ref_id
        for i, chunk in enumerate(ref_chunks):
            assert chunk.layout_tag == "reference"
            assert "参考文献" in chunk.content or f"[{i + 1}]" in chunk.content or "Author" in chunk.content

    def test_extracts_from_mineru_style_refs(self):
        """MinerU 风格的 ref_text 分块应正确提取。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="References",
                layout_tag="heading",
                section_title=None,
            ),
            _make_block(
                content=(
                    "[1] Zhang W, Liu Y. AI applications in forestry. "
                    "Journal of Forestry Research, 2023, 35(2): 200-215. "
                    "DOI: 10.1007/s11676-023-01600-0"
                ),
                layout_tag="reference",
                section_title=None,  # MinerU 可能不设置 section_title
                page_number=12,
            ),
            _make_block(
                content=(
                    "[2] Li H, Wang J. Digital twin framework. "
                    "IEEE Trans on Industrial Informatics, 2024, 20(1): 88-99."
                ),
                layout_tag="reference",
                section_title=None,
                page_number=12,
            ),
        ]

        results = svc.chunk_blocks(blocks)
        ref_chunks = [c for c in results if c.chunk_type == "reference"]

        assert len(ref_chunks) == 2, (
            f"期望 2 条参考文献，实际 {len(ref_chunks)} 条"
        )

    def test_references_preserve_section_title(self):
        """参考文献块应保留章节标题和路径信息。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="参考文献",
                layout_tag="heading",
                section_title=None,
                section_path="五、参考文献",
            ),
            _make_block(
                content="[1] 张三. 深度学习在NLP中的应用[J]. 软件学报, 2023.",
                layout_tag="reference",
                section_title="参考文献",
                section_path="五、参考文献",
                page_number=15,
            ),
        ]

        results = svc.chunk_blocks(blocks)
        ref_chunks = [c for c in results if c.chunk_type == "reference"]

        assert len(ref_chunks) >= 1
        # 参考文献应保留章节信息
        assert ref_chunks[0].section_title == "参考文献"


class TestReferenceExtractor:
    """ReferenceExtractor 解析测试。"""

    def test_extract_numbered_entries(self):
        entries = ReferenceExtractor.extract_entries(
            "[1] 张三, 李四. 数字孪生研究[J]. 计算机学报, 2023.\n"
            "[2] Smith J. AI applications[J]. Nature, 2024.\n"
            "[3] 王五. 深度学习[D]. 北京大学, 2022."
        )
        assert len(entries) == 3

    def test_extract_single_entry(self):
        entries = ReferenceExtractor.extract_entries(
            "[1] Zhang W, Liu Y. Title here. Journal Name, 2023."
        )
        assert len(entries) == 1
        assert entries[0].year == "2023"

    def test_empty_text(self):
        assert ReferenceExtractor.extract_entries("") == []
        assert ReferenceExtractor.extract_entries("   \n  ") == []

    def test_is_reference_section(self):
        assert ReferenceExtractor.is_reference_section("参考文献") is True
        assert ReferenceExtractor.is_reference_section("References") is True
        assert ReferenceExtractor.is_reference_section("Bibliography") is True
        assert ReferenceExtractor.is_reference_section("参考书目") is True
        assert ReferenceExtractor.is_reference_section("系统架构") is False
        assert ReferenceExtractor.is_reference_section("") is False
        assert ReferenceExtractor.is_reference_section(None) is False


class TestMergeTextStreamLayoutTag:
    """_merge_text_stream 保留 layout_tag 且不同标签不合并不丢失。"""

    def test_same_page_same_tag_merged_and_preserved(self):
        """同页同 layout_tag 合并后保留标签。"""
        svc = _make_chunker()
        blocks = [
            _make_block("正文段落一", layout_tag="body", page_number=1),
            _make_block("正文段落二", layout_tag="body", page_number=1),
        ]
        merged = svc._merge_text_stream(blocks)
        assert len(merged) == 1
        assert merged[0].layout_tag == "body"
        assert "正文段落一" in merged[0].content
        assert "正文段落二" in merged[0].content

    def test_same_page_different_tags_not_merged(self):
        """同页不同 layout_tag（body + reference）不应合并。"""
        svc = _make_chunker()
        blocks = [
            _make_block("正文内容", layout_tag="body", page_number=1),
            _make_block("[1] 张三. 某论文[J]. 某期刊, 2023.", layout_tag="reference", page_number=1),
        ]
        merged = svc._merge_text_stream(blocks)
        # 不同标签应分开，各保留语义
        assert len(merged) == 2, f"期望 2 个块，实际 {len(merged)}"
        tags = [b.layout_tag for b in merged]
        assert "body" in tags
        assert "reference" in tags

    def test_same_page_tag_none_merged(self):
        """同页一个 layout_tag=None 一个 body → 合并且保留有效标签。"""
        svc = _make_chunker()
        blocks = [
            _make_block("文本A", layout_tag=None, page_number=1),
            _make_block("文本B", layout_tag="body", page_number=1),
        ]
        merged = svc._merge_text_stream(blocks)
        assert len(merged) == 1
        assert merged[0].layout_tag == "body"

    def test_cross_page_different_tags_not_merged(self):
        """跨页不同 layout_tag 不应合并。"""
        svc = _make_chunker()
        blocks = [
            _make_block("上一页正文结尾。", layout_tag="body", page_number=9),
            _make_block("[1] 参考文献条目", layout_tag="reference", page_number=10),
        ]
        merged = svc._merge_text_stream(blocks)
        assert len(merged) == 2, f"期望 2 个块（跨页+不同标签），实际 {len(merged)}"
        assert merged[0].layout_tag == "body"
        assert merged[1].layout_tag == "reference"


class TestFuseBlocksLayoutTag:
    """_fuse_blocks 保留最具体 layout_tag 的测试。"""

    def test_fuse_preserves_reference_over_body(self):
        """融合时 reference 优先级高于 body。"""
        svc = _make_chunker()
        blocks = [
            _make_block("前文", layout_tag="body"),
            _make_block("[1] 张三. 标题[J]. 期刊.", layout_tag="reference"),
        ]
        fused = svc._fuse_blocks(blocks)
        assert fused.layout_tag == "reference", f"期望 'reference'，实际 '{fused.layout_tag}'"

    def test_fuse_single_block_unchanged(self):
        """单块融合不变。"""
        svc = _make_chunker()
        block = _make_block("单块", layout_tag="heading")
        fused = svc._fuse_blocks([block])
        assert fused is block
        assert fused.layout_tag == "heading"


class TestLooksLikeReferences:
    """内容级参考文献检测测试。"""

    def test_detects_numbered_doi_refs(self):
        """编号 + DOI 参考文献应被检测。"""
        text = "[1] Zhang W, Liu Y. AI applications. Journal of Forestry, 2023, 35(2): 200-215. DOI: 10.1007/s11676-023-01600-0"
        assert ChunkingService._looks_like_references(text) is True

    def test_detects_chinese_numbered_refs(self):
        """中文编号参考文献应被检测。"""
        text = "[1] 张三, 李四. 数字孪生系统架构研究[J]. 计算机学报, 2023, 46(3): 500-520."
        assert ChunkingService._looks_like_references(text) is True

    def test_detects_two_reference_entries(self):
        """两条参考文献组合应被检测。"""
        text = (
            "[1] 张三. 深度学习在NLP中的应用[J]. 软件学报, 2023.\n"
            "[2] 李四. 知识图谱研究综述[J]. 计算机研究与发展, 2024."
        )
        assert ChunkingService._looks_like_references(text) is True

    def test_rejects_short_text(self):
        """短文本（<80 字符）不应被误判。"""
        text = "[1] 张三. 标题. 2024."
        assert ChunkingService._looks_like_references(text) is False

    def test_rejects_body_text(self):
        """正文不应被误判为参考文献。"""
        text = "本文提出了一种基于深度学习的数字孪生系统架构，该系统采用分层设计模式，包括数据层、模型层和应用层三个核心组件。"
        assert ChunkingService._looks_like_references(text) is False

    def test_rejects_text_with_only_year(self):
        """仅包含年份的正文不应被误判。"""
        text = "自2020年以来，人工智能技术在林业领域的应用取得了显著进展。特别是2023年，大语言模型的出现为知识管理带来了新的可能性。"
        assert ChunkingService._looks_like_references(text) is False


class TestGroupBySectionContentFallback:
    """内容级兜底：无 section_title 且无 layout_tag 时的参考文献检测。"""

    def test_content_based_ref_detection_without_tags(self):
        """layout_tag=None 但内容明显是参考文献 → __REFERENCES__。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="[1] Zhang W, Liu Y. AI applications in forestry. "
                        "Journal of Forestry Research, 2023, 35(2): 200-215. "
                        "DOI: 10.1007/s11676-023-01600-0",
                layout_tag=None,
                section_title=None,
                page_number=10,
            ),
        ]
        groups = svc._group_by_section(blocks)
        assert len(groups) == 1
        assert groups[0][0] == "__REFERENCES__", (
            f"内容级检测失败: 期望 '__REFERENCES__'，实际 '{groups[0][0]}'"
        )

    def test_content_based_ref_detection_chinese(self):
        """中文编号引用，layout_tag 丢失 → 内容级兜底检测。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="[1] 张三, 李四. 数字孪生系统架构研究[J]. 计算机学报, 2023, 46(3): 500-520.",
                layout_tag=None,  # OCR 或 chars 回退产生的块通常没有 layout_tag
                section_title=None,
                page_number=11,
            ),
        ]
        groups = svc._group_by_section(blocks)
        assert groups[0][0] == "__REFERENCES__", f"实际 '{groups[0][0]}'"

    def test_body_text_without_tags_not_misclassified(self):
        """无标签的正文不应被误判为参考文献。"""
        svc = _make_chunker()
        blocks = [
            _make_block(
                content="系统架构采用微服务设计，每个服务独立部署并通过API网关进行通信。",
                layout_tag=None,
                section_title=None,
                page_number=5,
            ),
        ]
        groups = svc._group_by_section(blocks)
        # 正文不应被归入 __REFERENCES__
        assert groups[0][0] != "__REFERENCES__", (
            f"正文被误判为参考文献: key='{groups[0][0]}'"
        )
