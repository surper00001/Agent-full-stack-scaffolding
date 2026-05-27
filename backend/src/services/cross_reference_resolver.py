"""
图文交叉引用锚点解析器。

从文本块中提取「如图 3-2 / Figure 3-2 / 见表 2-1」等引用，
匹配对应的图片/表格块，建立双向链接。
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.services.chunking_service import StructuredBlock

# ── 引用模式 ──────────────────────────────────────────────

# 图片引用: 如图3-2, 见图3.2, 如图3-2所示, Figure 3-2, Fig. 3.2, see Fig. 3-2
_CN_IMAGE_REF = re.compile(
    r"(?:如|参见?|见|参照)\s*(?:图|图片|附图|图例)\s*(\d+(?:[\.\-]\d+)*)\s*(?:所示|所描述|示意)?",
)
_EN_IMAGE_REF = re.compile(
    r"(?:see\s+|refer\s+to\s+)?(?:Figure|Fig\.?)\s*(\d+(?:[\.\-]\d+)*)",
    re.IGNORECASE,
)
# 表格引用: 如表3-1, Table 3-1, see Table 3.1
_CN_TABLE_REF = re.compile(
    r"(?:如|参见?|见|参照)\s*(?:表|表格|附表)\s*(\d+(?:[\.\-]\d+)*)\s*(?:所示|所描述|示意)?",
)
_EN_TABLE_REF = re.compile(
    r"(?:see\s+|refer\s+to\s+)?(?:Table)\s*(\d+(?:[\.\-]\d+)*)",
    re.IGNORECASE,
)

# 从 caption 中提取编号: 图3-2, Figure 3-2, 表1, Table 1
_CAPTION_FIGURE_NUM = re.compile(
    r"(?:图|图片|Figure|Fig\.?)\s*(\d+(?:[\.\-]\d+)*)",
    re.IGNORECASE,
)
_CAPTION_TABLE_NUM = re.compile(
    r"(?:表|表格|Table)\s*(\d+(?:[\.\-]\d+)*)",
    re.IGNORECASE,
)


def _normalize_ref_id(raw: str) -> str:
    """统一引用编号格式：3-2 和 3.2 归一化为同一格式。"""
    return raw.replace("-", ".").strip()


@dataclass
class CrossReference:
    """一条交叉引用记录。"""

    source_block_idx: int  # 引用所在的源块索引
    ref_type: str  # "image" | "table"
    ref_text: str  # 原始引用文本，如 "图3-2"
    ref_number: str  # 归一化编号，如 "3.2"
    target_caption: str | None = None  # 匹配到的目标标题
    target_page: int | None = None


class CrossReferenceResolver:
    """解析图文交叉引用并建立双向链接。"""

    @classmethod
    def resolve(
        cls, blocks: list[StructuredBlock]
    ) -> list[StructuredBlock]:
        """扫描所有块，为包含交叉引用的文本块建立到图片/表格块的链接。

        返回修改后的 blocks 列表（原地修改，同时返回）。
        """
        if not blocks:
            return blocks

        # 第一阶段：建立图片/表格块的编号索引
        figure_index: dict[str, int] = {}  # normalized_number -> block_idx
        table_index: dict[str, int] = {}

        for i, block in enumerate(blocks):
            if block.block_type == "image" or block.layout_tag == "image":
                caption = block.image_caption or block.content or ""
                num = cls._extract_figure_number(caption)
                if num:
                    figure_index[_normalize_ref_id(num)] = i

            elif block.block_type == "table":
                caption = block.table_caption or block.content or ""
                num = cls._extract_table_number(caption)
                if num:
                    table_index[_normalize_ref_id(num)] = i

        if not figure_index and not table_index:
            return blocks

        # 第二阶段：扫描文本块，匹配引用
        refs_by_source: dict[int, list[CrossReference]] = defaultdict(list)

        for i, block in enumerate(blocks):
            if block.block_type != "text":
                continue

            content = block.content
            refs: list[CrossReference] = []

            # 图片引用
            for match in _CN_IMAGE_REF.finditer(content):
                num = _normalize_ref_id(match.group(1))
                refs.append(CrossReference(
                    source_block_idx=i,
                    ref_type="image",
                    ref_text=match.group(0),
                    ref_number=num,
                ))
            for match in _EN_IMAGE_REF.finditer(content):
                num = _normalize_ref_id(match.group(1))
                refs.append(CrossReference(
                    source_block_idx=i,
                    ref_type="image",
                    ref_text=match.group(0),
                    ref_number=num,
                ))

            # 表格引用
            for match in _CN_TABLE_REF.finditer(content):
                num = _normalize_ref_id(match.group(1))
                refs.append(CrossReference(
                    source_block_idx=i,
                    ref_type="table",
                    ref_text=match.group(0),
                    ref_number=num,
                ))
            for match in _EN_TABLE_REF.finditer(content):
                num = _normalize_ref_id(match.group(1))
                refs.append(CrossReference(
                    source_block_idx=i,
                    ref_type="table",
                    ref_text=match.group(0),
                    ref_number=num,
                ))

            if refs:
                refs_by_source[i] = refs

        # 第三阶段：解析目标
        total_matched = 0
        for src_idx, refs in refs_by_source.items():
            image_refs: list[str] = []
            table_refs: list[str] = []
            source_block = blocks[src_idx]

            for ref in refs:
                target_idx: int | None = None
                if ref.ref_type == "image":
                    target_idx = figure_index.get(ref.ref_number)
                elif ref.ref_type == "table":
                    target_idx = table_index.get(ref.ref_number)

                if target_idx is not None:
                    target_block = blocks[target_idx]
                    ref.target_caption = (
                        target_block.image_caption
                        or target_block.table_caption
                        or target_block.content[:80]
                    )
                    ref.target_page = target_block.page_number
                    total_matched += 1

                    # 在文本块中标记引用的图片/表格 chunk（供后续 chunking 阶段使用）
                    # 这里用 target 的 chunk 占位 —— 实际 chunk_id 在分块后才生成
                    # 暂时用 "(figure|table):{page_number}" 格式标记
                    tag = f"{ref.ref_type}:{target_block.page_number}:{ref.ref_number}"
                    if ref.ref_type == "image" and tag not in image_refs:
                        image_refs.append(tag)
                    elif ref.ref_type == "table" and tag not in table_refs:
                        table_refs.append(tag)

            # 将交叉引用信息附加到源文本块（供 chunking 使用）
            if image_refs and not source_block.image_refs:
                source_block.image_refs = image_refs
            if table_refs and not source_block.table_refs:
                source_block.table_refs = table_refs

        if total_matched > 0:
            logger.info(
                f"交叉引用解析: {total_matched} 条匹配, "
                f"涉及 {len(refs_by_source)} 个源块"
            )

        return blocks

    @classmethod
    def _extract_figure_number(cls, caption: str) -> str | None:
        """从图片标题中提取编号，如 '图 3-2 系统架构' → '3-2'。"""
        match = _CAPTION_FIGURE_NUM.search(caption)
        return match.group(1) if match else None

    @classmethod
    def _extract_table_number(cls, caption: str) -> str | None:
        """从表格标题中提取编号，如 '表 1 实验结果' → '1'。"""
        match = _CAPTION_TABLE_NUM.search(caption)
        return match.group(1) if match else None
