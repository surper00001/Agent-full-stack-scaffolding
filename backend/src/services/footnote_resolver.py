"""
脚注/尾注解析器 —— 建立正文标记到脚注内容的链接。

支持格式：
- 上标数字/符号: ¹²³, ①②③, [1], *
- 页脚脚注: 与正文同页、匹配编号
- 尾注: 在文档末尾独立 section
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.services.chunking.data_models import StructuredBlock

from src.services.document_processors.layout import LayoutTag

# 正文中的脚注标记: ① ② ③, ¹²³, [1], (1), *, †, ‡
_INLINE_FOOTNOTE_MARKER = re.compile(
    r"[①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺❻❼❽❾❿]"
    r"|[¹²³⁴⁵⁶⁷⁸⁹⁰]"
    r"|\[\d+\]"
    r"|(?<!\w)[\*†‡§¶](?!\w)",
)

# 脚注块开头编号: ①, 1., [1], *, †
_FOOTNOTE_HEADER = re.compile(
    r"^[①②③④⑤⑥⑦⑧⑨⑩❶❷❸❹❺❻❼❽❾❿]"
    r"|^[¹²³⁴⁵⁶⁷⁸⁹⁰]"
    r"|^\[\d+\]"
    r"|^(?:\d+[\.\、\)])"
    r"|^[\*†‡§¶]\s",
)


def _normalize_footnote_marker(marker: str) -> str:
    """归一化脚注标记（用于匹配）。"""
    # 上标数字 → 普通数字
    sup_map = {
        "¹": "1", "²": "2", "³": "3", "⁴": "4", "⁵": "5",
        "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9", "⁰": "0",
    }
    circled_map = {
        "①": "1", "②": "2", "③": "3", "④": "4", "⑤": "5",
        "⑥": "6", "⑦": "7", "⑧": "8", "⑨": "9", "⑩": "10",
        "❶": "1", "❷": "2", "❸": "3", "❹": "4", "❺": "5",
        "❻": "6", "❼": "7", "❽": "8", "❾": "9", "❿": "10",
    }
    marker = marker.strip()
    for old, new in {**sup_map, **circled_map}.items():
        marker = marker.replace(old, new)
    # 去掉括号
    marker = marker.strip("[]（）()")
    return marker.strip()


class FootnoteResolver:
    """脚注/尾注匹配器。"""

    @classmethod
    def resolve(
        cls, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """扫描脚注并建立正文↔脚注的链接关系。"""
        if not blocks:
            return blocks

        # 收集脚注/尾注块（按页码索引）
        footnote_blocks: dict[int, list[tuple[int, StructuredBlock]]] = defaultdict(list)

        for i, block in enumerate(blocks):
            tag = block.layout_tag or ""
            if tag == LayoutTag.FOOTNOTE.value:
                footnote_blocks[block.page_number].append((i, block))

        if not footnote_blocks:
            return blocks

        # 匹配正文标记到脚注
        total_linked = 0
        for block in blocks:
            if block.block_type != "text" and block.layout_tag != LayoutTag.BODY.value:
                continue

            content = block.content
            markers_found = _INLINE_FOOTNOTE_MARKER.findall(content)
            if not markers_found:
                continue

            page = block.page_number
            page_fns = footnote_blocks.get(page, [])
            if not page_fns:
                continue

            fn_refs: list[str] = []
            for marker in markers_found:
                norm_marker = _normalize_footnote_marker(marker)
                for _fn_idx, fn_block in page_fns:
                    fn_header_match = _FOOTNOTE_HEADER.match(fn_block.content.strip())
                    if fn_header_match:
                        fn_norm = _normalize_footnote_marker(fn_header_match.group(0))
                        if fn_norm == norm_marker:
                            ref_tag = f"footnote:{fn_block.page_number}:{norm_marker}"
                            if ref_tag not in fn_refs:
                                fn_refs.append(ref_tag)
                            total_linked += 1

            if fn_refs and not block.image_refs:
                block.image_refs = fn_refs

        if total_linked > 0:
            logger.info(f"脚注链接: {total_linked} 条匹配")

        return blocks
