"""分隔符策略配置 — 按文档类型的自适应分隔符选择。

从 ChunkingService 提取为独立模块（纯数据，无逻辑）。
"""

from __future__ import annotations

import re

# ── 动态分隔符策略（按文档类型分层降级） ──

# 通用语义分隔符（中文 + 混合）
SEPARATORS_SEMANTIC = [
    "\n## ", "\n### ", "\n#### ", "\n##### ",
    "\n第[一二三四五六七八九十百千]+[章节篇部]",
    "\n\n", "\n\r\n",
    "。\n", "；\n", "！\n", "？\n",
    "。", "！", "？", "；",
    ". ", "! ", "? ", ".\n",
    "  ", " ",
    "",
]

# 通用递归分隔符（不带中文章节标记的正则）
SEPARATORS_STANDARD = [
    "\n## ", "\n### ", "\n#### ",
    "\n\n", "\n",
    "。", "！", "？", "；",
    "  ", " ", ". ", "! ", "? ",
    "",
]

# 学术论文：标题层级优先，保留摘要/结论完整性
SEPARATORS_ACADEMIC = [
    "\n## ", "\n### ", "\n#### ",
    "\n第[一二三四五六七八九十百千]+[章节篇部]",
    "\n(?:Abstract|Introduction|Method|Experiment|Result|Conclusion|Reference)",
    "\n\n",
    "。\n", "；\n",
    "。", "！", "？",
    ". ", "  ", " ",
    "",
]

# 法律/合同：条款编号优先，小粒度精确分割
SEPARATORS_LEGAL = [
    r"\n第[一二三四五六七八九十百千\d]+[条款章节]",
    r"\n\d+[\.\、]\d+[\.\、]",  # 条款编号 1.1.1
    r"\n[（(][一二三四五六七八九十\d]+[）)]",
    "\n\n",
    "。", "；",
    "  ", " ",
    "",
]

# 技术文档：标题 + 代码块边界，大粒度保留上下文
SEPARATORS_TECHNICAL = [
    "\n## ", "\n### ", "\n#### ",
    "\n\n", "\n```",
    "。\n", "\n",
    "。", "！", "？",
    "  ", ". ",
    "",
]

# 报告/白皮书：章节 + 段落，中等粒度
SEPARATORS_REPORT = [
    "\n## ", "\n### ",
    "\n第[一二三四五六七八九十百千]+[章节篇部]",
    "\n\n",
    "。\n", "\n",
    "。", "！", "？",
    "  ", ". ", " ",
    "",
]

# 正则分隔符（需 re.split，不能用 str.split）
REGEX_SEPARATORS = {
    r"\n第[一二三四五六七八九十百千]+[章节篇部]",
    r"\n第[一二三四五六七八九十百千\d]+[条款章节]",
    r"\n\d+[\.\、]\d+[\.\、]",
    r"\n(?:Abstract|Introduction|Method|Experiment|Result|Conclusion|Reference)",
}

# 文档类型 → 分隔符策略
CATEGORY_SEPARATORS: dict[str, list[str]] = {
    "academic": SEPARATORS_ACADEMIC,
    "legal": SEPARATORS_LEGAL,
    "technical": SEPARATORS_TECHNICAL,
    "report": SEPARATORS_REPORT,
    "markdown": SEPARATORS_SEMANTIC,
}

# 编译后的正则模式（模块级预编译，避免重复）
CHINESE_CHAR_PATTERN = re.compile(r"[一-鿿㐀-䶿]")
CHINESE_PUNCT = re.compile(r"[。！？；，、：""''（）【】《》…—　]")
HEADING_PATTERN = re.compile(
    r"^(#{1,6}\s+|第[一二三四五六七八九十百千\d]+[章节篇部条]|"
    r"\d+(?:\.\d+)*\s+[A-Z一-鿿]|[（(][一二三四五六七八九十\d]+[）)])",
    re.MULTILINE,
)
CODE_BLOCK_PATTERN = re.compile(r"```[\s\S]*?```|~~~[\s\S]*?~~~")
LIST_PATTERN = re.compile(r"^[\s]*[-*+]\s+|^[\s]*\d+[\.\、]\s+", re.MULTILINE)
