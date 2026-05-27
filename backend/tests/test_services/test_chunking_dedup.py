"""
分块去重测试 —— 验证 _force_split + _apply_overlap 双重重叠 BUG 已修复。

BUG 描述：
_force_split 通过 step 移动（step = chunk_size - chunk_overlap）已产生自然重叠，
但末尾又调用 _apply_overlap 添加重叠，导致同一段文本在相邻 chunk 中重复出现。
严重时一段话可重复 5-7 次。

注意：_char_count 对中文字符按 1 计算，英文/数字按 1/4 计算，
测试文本设计需考虑此权重差异。
"""

from __future__ import annotations

from src.services.chunking_service import ChunkingService


def _make_chunker(
    child_size: int = 768, child_overlap: int = 128, doc_category: str = "general"
) -> ChunkingService:
    """创建测试用 ChunkingService。"""
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


def _make_long_cn_text(sentence_count: int = 30, chars_per_sentence: int = 30) -> str:
    """生成足够长的中文测试文本。"""
    template = (
        "第{idx}部分内容涉及系统架构设计、数据处理流程优化、"
        "以及用户交互界面改进方案等关键技术要点和实施策略"
    )
    parts = []
    for i in range(sentence_count):
        parts.append(template.format(idx=i))
    return "。".join(parts) + "。"


class TestForceSplitNoDuplication:
    """_force_split 不应产生重复内容。"""

    def test_short_text_no_duplication(self):
        """小于 chunk_size 的文本不拆分，更不应有重复。"""
        svc = _make_chunker(child_size=200, child_overlap=32)
        text = "这是一段短测试文本长度远小于分块大小所以不分块"
        chunks = svc._force_split(text, 200, 32)
        assert len(chunks) == 1
        assert chunks[0] == text

    def test_long_text_overlap_within_bounds(self):
        """长文本分块后，相邻 chunk 的重叠量应 ≤ chunk_overlap。

        step 移动产生自然重叠 32 字符是合法的。
        BUG 产生的双重重叠会让重叠量 > chunk_overlap。
        """
        svc = _make_chunker(child_size=200, child_overlap=32)
        text = _make_long_cn_text(sentence_count=30, chars_per_sentence=30)

        chunks = svc._force_split(text, 200, 32)

        assert len(chunks) >= 4, f"应拆分为多个 chunk，实际 {len(chunks)}"

        # 验证：相邻 chunk 不共享超过 chunk_overlap + 容差 的字符
        max_allowed_overlap = 32 + 10  # chunk_overlap + 容差（标点边界调整）

        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            overlap_found = 0
            # 找到前一块尾部与当前块头部的最长公共前缀
            for test_len in range(min(len(prev), len(curr)), 0, -1):
                if prev[-test_len:] == curr[:test_len]:
                    overlap_found = test_len
                    break

            assert overlap_found <= max_allowed_overlap, (
                f"❌ Chunk[{i - 1}] → Chunk[{i}] 重叠 {overlap_found} 字符，"
                f"超过上限 {max_allowed_overlap}！疑似双重重叠\n"
                f"  Chunk[{i - 1}] 尾: …{prev[-50:]}\n"
                f"  Chunk[{i}]   头: {curr[:50]}…"
            )

    def test_overlap_is_step_based_not_text_duplication(self):
        """重叠应是 step 移动产生的自然重叠，不应是可识别的大段重复。

        合法：step=200-32=168 → Chunk1 从 text[168:] 开始，天然重叠 32 字符
        非法：Chunk1 中将 Chunk0 末尾的完整子串重复一遍
        """
        svc = _make_chunker(child_size=200, child_overlap=32)

        text = _make_long_cn_text(sentence_count=40, chars_per_sentence=25)

        chunks = svc._force_split(text, 200, 32)

        # 总分块长度应在合理范围
        total_chunk_len = sum(len(c) for c in chunks)
        max_expected = len(text) + 32 * (len(chunks) - 1)  # 合法重叠上限
        assert total_chunk_len <= max_expected * 1.05, (
            f"总分块长度 {total_chunk_len} 超过预期 {max_expected}，疑似双重重叠"
        )

    def test_each_chunk_has_unique_content(self):
        """每个 chunk 应包含前一个 chunk 没有的独有内容段。"""
        svc = _make_chunker(child_size=200, child_overlap=32)

        text = _make_long_cn_text(sentence_count=40, chars_per_sentence=25)

        chunks = svc._force_split(text, 200, 32)

        seen = set()
        for chunk in chunks:
            seen.add(chunk)

        assert len(seen) == len(chunks), (
            f"存在完全重复的 chunk: {len(chunks)} chunks → {len(seen)} 唯一"
        )


class TestRecursiveSplitNoDuplication:
    """_recursive_split 组合调用也不应产生重复。"""

    def test_recursive_split_overlap_within_bounds(self):
        """验证 _split_text → _recursive_split 的重叠量 ≤ chunk_overlap。"""
        svc = _make_chunker(child_size=200, child_overlap=32)

        body = _make_long_cn_text(sentence_count=20, chars_per_sentence=25)
        text = (
            "## 第一章 系统概述\n\n"
            + body[:500]
            + "\n\n## 第二章 技术架构\n\n"
            + body[500:]
            + "\n\n"
        )

        chunks = svc._split_text(text, 200, 32)

        assert len(chunks) >= 4

        max_allowed = 32 + 20  # chunk_overlap + 分隔符边界容差
        for i in range(1, len(chunks)):
            prev = chunks[i - 1]
            curr = chunks[i]
            overlap_found = 0
            for test_len in range(min(len(prev), len(curr)), 0, -1):
                if prev[-test_len:] == curr[:test_len]:
                    overlap_found = test_len
                    break

            assert overlap_found <= max_allowed, (
                f"❌ 递归分块 Chunk[{i - 1}] → Chunk[{i}] "
                f"重叠 {overlap_found} 字符，超过 {max_allowed}"
            )


class TestApplyOverlapDedup:
    """_apply_overlap 去重检测。"""

    def test_normal_overlap_adds_tail(self):
        """正常情况：chunk1 头部 ≠ chunk0 尾部时，_apply_overlap 应正常添加。"""
        svc = _make_chunker()

        chunk0 = "前文内容部分比较长的填充文本" * 3 + "重叠区文本标识"
        chunk1 = "全新内容开始没有任何重叠部分继续延伸更多文字信息"

        chunks = [chunk0, chunk1]
        result = svc._apply_overlap(chunks, chunk_overlap=15)

        # result[1] 应比 chunk1 长（添加了重叠尾部）
        assert len(result[1]) > len(chunk1), (
            f"正常情况应添加 overlap: len(result[1])={len(result[1])} <= {len(chunk1)}"
        )

    def test_apply_overlap_does_not_corrupt_content(self):
        """_apply_overlap 不应产生内容损坏（如 chunk0 内容全量重复）。"""
        svc = _make_chunker()

        chunk0 = _make_long_cn_text(sentence_count=8, chars_per_sentence=25)
        chunk1 = _make_long_cn_text(sentence_count=5, chars_per_sentence=25)

        chunks = [chunk0, chunk1]
        result = svc._apply_overlap(chunks, chunk_overlap=30)

        # result[1] 不应以整个 chunk0 开头
        assert not result[1].startswith(chunk0[:50]), (
            f"result[1] 不应以 chunk0 内容全量开头"
        )
        # result[1] 应包含 chunk1 的核心内容
        chunk1_core = chunk1[10:30]
        assert chunk1_core in result[1], (
            f"result[1] 应包含 chunk1 核心内容 '{chunk1_core}'"
        )
