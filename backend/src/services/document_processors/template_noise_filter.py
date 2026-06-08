"""模板噪声去重 — 检测并标记跨页重复出现的模板噪声（水印、版权声明等）。

从 TableUtilsMixin._deduplicate_template_noise 提取为独立模块。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from loguru import logger

from src.services.document_processors.layout import LayoutTag

if TYPE_CHECKING:
    from src.services.chunking_service import StructuredBlock


def deduplicate_template_noise(blocks: list[StructuredBlock]) -> list[StructuredBlock]:
    """检测并标记跨页重复出现的模板噪声。

    算法：
    1. 收集所有 text 块中的短句片段（10-250 字符）
    2. 找出出现在 ≥3 个不同页面的重复片段
    3. 将这些片段所在块标记为 TEMPLATE_NOISE
    4. 从块内容中移除重复片段

    典型场景：
    - 每页相同的 "Confidential - Do Not Distribute" 水印
    - 每页相同的版权声明行
    - 模板中的固定警告语
    """
    if not blocks or len(blocks) < 3:
        return blocks

    # 阶段1: 收集候选片段（每块拆分为短句，并做归一化指纹）
    # fingerprint → {page: [block_indices]}
    fp_pages: dict[str, set[int]] = {}
    fp_blocks: dict[str, list[int]] = {}  # fingerprint → [block_idx]
    # block_idx → [(original_text, fingerprint)]
    block_segments: dict[int, list[tuple[str, str]]] = {}

    for idx, block in enumerate(blocks):
        if block.block_type != "text":
            continue
        if block.layout_tag in ("header", "footer"):
            continue

        content = block.content
        # 将文本拆分为短句（按句末标点或换行）
        segments = re.split(r"[。！？\n]+", content)
        for seg in segments:
            seg = seg.strip()
            if len(seg) < 10 or len(seg) > 250:
                continue
            # 归一化指纹：去除空格和标点，转小写
            fp = re.sub(r"\s+", "", seg).lower()
            if len(fp) < 10:
                continue
            fp_pages.setdefault(fp, set()).add(block.page_number)
            fp_blocks.setdefault(fp, []).append(idx)
            block_segments.setdefault(idx, []).append((seg, fp))

    # 阶段2: 标记跨 ≥3 页重复的指纹
    noise_fingerprints: set[str] = set()
    for fp, pages in fp_pages.items():
        if len(pages) >= 3:
            noise_fingerprints.add(fp)

    if not noise_fingerprints:
        return blocks

    # 阶段3: 移除噪声段并标记块
    affected_blocks = 0
    for idx, segments in block_segments.items():
        block = blocks[idx]
        noise_segments_in_block = [
            orig for orig, fp in segments if fp in noise_fingerprints
        ]
        if not noise_segments_in_block:
            continue

        # 移除噪声段
        cleaned = block.content
        for ns in noise_segments_in_block:
            cleaned = cleaned.replace(ns, "").strip()

        # 清理多余空白
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"  +", " ", cleaned)

        if len(cleaned) < 10:
            # 整块都是噪声 → 标记但不删除（前端可能仍需显示页码信息）
            block.layout_tag = LayoutTag.TEMPLATE_NOISE.value
        elif len(cleaned) < len(block.content) * 0.6:
            # 噪声占比 >40% → 整块标记
            block.layout_tag = LayoutTag.TEMPLATE_NOISE.value
        # 否则只清理内容，保留原标签

        # 更新 content
        object.__setattr__(block, "content", cleaned)
        affected_blocks += 1

    if affected_blocks:
        logger.info(
            f"模板噪声去重: {len(noise_fingerprints)} 种噪声模式, "
            f"影响 {affected_blocks} 个块"
        )

    return blocks
