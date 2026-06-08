"""
Chunking 工具包 — 从 ChunkingService 提取的独立工具模块。

- truncator: 内容截断、字符计数、代码语言检测
"""

from src.services.chunking.truncator import (
    advance_by_char_count,
    char_count,
    detect_code_language,
    hard_cap_content,
    tail_by_char_count,
    truncate_content_for_embed,
)

__all__ = [
    "hard_cap_content",
    "truncate_content_for_embed",
    "char_count",
    "advance_by_char_count",
    "tail_by_char_count",
    "detect_code_language",
]
