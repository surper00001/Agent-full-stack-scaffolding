"""模板噪声去重单元测试。

覆盖场景：
- 跨 ≥3 页重复的噪声片段检测与移除
- 不足 3 页不视为噪声
- header/footer 块跳过
- 整块被标记为 TEMPLATE_NOISE 的场景
- 混合非文本块的处理
"""

from __future__ import annotations

import pytest

from src.services.chunking.data_models import StructuredBlock
from src.services.document_processors.layout import LayoutTag
from src.services.document_processors.table_utils import TableUtilsMixin


def _text_block(content: str, page: int, layout_tag: str | None = None) -> StructuredBlock:
    return StructuredBlock(
        block_type="text", content=content, page_number=page, layout_tag=layout_tag
    )


def _table_block(page: int) -> StructuredBlock:
    return StructuredBlock(
        block_type="table",
        content="",
        page_number=page,
        table_data=[["A", "B"], ["1", "2"]],
    )


@pytest.mark.unit
class TestTemplateNoiseBasic:
    """基础噪声检测与移除。"""

    def test_tripage_noise_removed(self) -> None:
        """同一个噪声片段出现在 3 个页面时被移除。"""
        noise = "Confidential - Do Not Distribute"
        blocks = [
            _text_block(f"{noise}\n这是第一页的正文内容。", page=1),
            _text_block(f"{noise}\n这是第二页的正文内容。", page=2),
            _text_block(f"{noise}\n这是第三页的正文内容。", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert noise not in block.content
            assert "正文内容" in block.content

    def test_noise_on_two_pages_kept(self) -> None:
        """只出现在 2 页不算噪声，内容应保留。"""
        noise = "This is a short notice."
        blocks = [
            _text_block(f"{noise}\nPage one content.", page=1),
            _text_block(f"{noise}\nPage two content.", page=2),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert noise in block.content

    def test_noise_segments_split_by_newline(self) -> None:
        """噪声按换行拆分为段，分别检测。"""
        noise1 = "版权所有 © 2024 某某科技公司"
        noise2 = "内部资料注意保密严禁外传转发"
        blocks = [
            _text_block(f"{noise1}\n{noise2}\n正文第 1 页", page=1),
            _text_block(f"{noise1}\n{noise2}\n正文第 2 页", page=2),
            _text_block(f"{noise1}\n{noise2}\n正文第 3 页", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert noise1 not in block.content
            assert noise2 not in block.content
            assert "正文" in block.content


@pytest.mark.unit
class TestTemplateNoiseEdgeCases:
    """边界条件。"""

    def test_short_segment_ignored(self) -> None:
        """太短的片段（< 15 字符）不会被检测为噪声。"""
        short = "Short"  # 5 字符
        blocks = [
            _text_block(f"{short}\nPage 1 content here.", page=1),
            _text_block(f"{short}\nPage 2 content here.", page=2),
            _text_block(f"{short}\nPage 3 content here.", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        # Short 太短，不会被收集
        for block in result:
            assert "Short" in block.content

    def test_long_segment_ignored(self) -> None:
        """太长片段（> 250 字符）不会被检测为噪声。"""
        long_text = "A" * 300
        blocks = [
            _text_block(f"{long_text}\n正文第 1 页", page=1),
            _text_block(f"{long_text}\n正文第 2 页", page=2),
            _text_block(f"{long_text}\n正文第 3 页", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert long_text in block.content

    def test_not_enough_blocks(self) -> None:
        """块数不足时不处理。"""
        blocks = [_text_block("内容", page=1)]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        assert result == blocks


@pytest.mark.unit
class TestTemplateNoiseTags:
    """噪声块标签标记。"""

    def test_entire_block_noise_tagged(self) -> None:
        """整块都是噪声时标记为 TEMPLATE_NOISE。"""
        noise = "未经授权不得复制或传播"
        blocks = [
            _text_block(noise, page=1),
            _text_block(noise, page=2),
            _text_block(noise, page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert block.layout_tag == LayoutTag.TEMPLATE_NOISE.value

    def test_heavily_affected_block_tagged(self) -> None:
        """噪声占比 >40% 时整块标记为 TEMPLATE_NOISE。"""
        noise = "内部机密文件 - 严禁外传"
        blocks = [
            _text_block(f"{noise}\n简短正文", page=1),
            _text_block(f"{noise}\n简短正文", page=2),
            _text_block(f"{noise}\n简短正文", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert block.layout_tag == LayoutTag.TEMPLATE_NOISE.value

    def test_header_block_skipped(self) -> None:
        """Header 块不参与噪声检测。"""
        noise = "第 X 页"
        blocks = [
            _text_block(noise, page=1, layout_tag=LayoutTag.HEADER.value),
            _text_block(noise, page=2, layout_tag=LayoutTag.HEADER.value),
            _text_block(noise, page=3, layout_tag=LayoutTag.HEADER.value),
            _text_block("正文内容", page=1),
            _text_block("正文内容", page=2),
            _text_block("正文内容", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        # header 块的内容不受影响（被跳过）
        for block in result:
            if block.layout_tag == LayoutTag.HEADER.value:
                assert noise in block.content

    def test_footer_block_skipped(self) -> None:
        """Footer 块不参与噪声检测。"""
        noise = "© 2024 Company Inc."
        blocks = [
            _text_block(noise, page=1, layout_tag=LayoutTag.FOOTER.value),
            _text_block(noise, page=2, layout_tag=LayoutTag.FOOTER.value),
            _text_block(noise, page=3, layout_tag=LayoutTag.FOOTER.value),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert noise in block.content


@pytest.mark.unit
class TestTemplateNoiseMixed:
    """混合块类型场景。"""

    def test_non_text_blocks_preserved(self) -> None:
        """非文本块不受影响。"""
        blocks = [
            _table_block(page=1),
            _table_block(page=2),
            _text_block("Confidential Notice\n正文页 1", page=1),
            _text_block("Confidential Notice\n正文页 2", page=2),
            _text_block("Confidential Notice\n正文页 3", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        # 表格块保持不变
        assert result[0].block_type == "table"
        assert result[1].block_type == "table"
        # 文本块的噪声被移除
        for i in range(2, 5):
            assert "Confidential Notice" not in result[i].content

    def test_noise_across_different_block_sizes(self) -> None:
        """噪声片段出现在不同大小的块中均被移除。"""
        noise = "All Rights Reserved"
        blocks = [
            _text_block(f"{noise}\n短正文", page=1),
            _text_block(f"{noise}\n这是第 2 页的比较长的正文内容，包含更多文字。", page=2),
            _text_block(f"{noise}\n第 3 页正文", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        for block in result:
            assert noise not in block.content

    def test_varying_whitespace_normalized(self) -> None:
        """空格差异被归一化后仍能检测。"""
        blocks = [
            _text_block("Confidential Notice\n正文页 1", page=1),
            _text_block("Confidential  Notice\n正文页 2", page=2),
            _text_block("Confidential   Notice\n正文页 3", page=3),
        ]
        result = TableUtilsMixin._deduplicate_template_noise(blocks)
        # 去除空格后的指纹相同，都应被移除
        for block in result:
            assert "Confidential" not in block.content
