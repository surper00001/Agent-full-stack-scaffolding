"""
文档类型分析器 —— Agentic RAG 核心。

自动识别文档结构类型、章节层级、内容分布，选择最优处理策略。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable


class DocCategory(str, Enum):  # noqa: UP042
    """文档大类。"""
    ACADEMIC = "academic"      # 学术论文（摘要、引言、方法、实验、结论）
    TECHNICAL = "technical"    # 技术文档/手册（API 文档、代码示例）
    LEGAL = "legal"            # 法律/合同（条款编号、章节结构）
    REPORT = "report"          # 报告/白皮书（执行摘要、分析、建议）
    GENERAL = "general"        # 通用文章/博客
    MARKDOWN = "markdown"      # Markdown 技术文档（# 标题层级）


@dataclass
class DocStructure:
    """文档结构描述。"""

    category: DocCategory
    confidence: float  # 0.0 ~ 1.0
    total_pages: int = 0
    # 章节层级
    headings: list[HeadingNode] = field(default_factory=list)
    # 内容统计
    text_ratio: float = 0.0       # 纯文本占比
    table_count: int = 0
    image_count: int = 0
    code_block_count: int = 0
    # 元数据
    detected_lang: str = "zh"     # zh / en / mixed
    key_patterns: list[str] = field(default_factory=list)  # 匹配到的特征模式
    # 推荐策略
    recommended_chunk_size: int = 500
    recommended_chunk_overlap: int = 50
    use_parent_chunking: bool = True
    preserve_table_context: bool = True
    merge_small_paragraphs: bool = True
    extra_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def has_toc(self) -> bool:
        return len(self.headings) > 0

    @property
    def is_mixed_content(self) -> bool:
        return self.table_count > 0 or self.image_count > 0 or self.code_block_count > 0


@dataclass
class HeadingNode:
    """章节/标题节点。"""
    level: int           # 1=h1, 2=h2, ...
    title: str
    page: int | None = None
    children: list[HeadingNode] = field(default_factory=list)
    start_offset: int = 0
    end_offset: int = 0
    _parent: HeadingNode | None = field(default=None, repr=False)

    def to_path(self) -> str:
        """返回层级路径，如 '第一章 > 1.1 概述 > 1.1.1 背景'。"""
        parts = [self.title]
        node = self
        while hasattr(node, "_parent") and node._parent is not None:
            node = node._parent
            parts.insert(0, node.title)
        return " > ".join(parts)


class DocumentTypeAnalyzer:
    """智能文档类型分析器。

    基于内容特征（标题层级、关键词、句式、结构密度）识别文档类型，
    并推荐最优的分块和处理策略。
    """

    # 学术论文特征
    _ACADEMIC_PATTERNS = [
        (r"(?i)\babstract\b|摘要|内容提要", 0.3),
        (r"(?i)\bintroduction\b|引言|前言|绪论", 0.25),
        (r"(?i)\bmethod(s|ology)?\b|研究方法|实验方法", 0.25),
        (r"(?i)\bexperiment(s|al)?\b|实验设计|实验过程", 0.25),
        (r"(?i)\bresult(s)?\b|实验结果|结果分析", 0.25),
        (r"(?i)\bconclusion\b|结论|总结与展望", 0.3),
        (r"(?i)\breference(s)?\b|参考文献", 0.3),
        (r"(?i)\backnowledg(e)?ment(s)?\b|致谢", 0.15),
        (r"(?i)\bkeyword(s)?\b[：:]|关键词[：:]", 0.2),
        (r"\bDOI[：:]\s*10\.", 0.4),
    ]

    # 法律/合同特征
    _LEGAL_PATTERNS = [
        (r"第[一二三四五六七八九十百千\d]+条|第[一二三四五六七八九十百千\d]+章|第[一二三四五六七八九十百千\d]+节", 0.35),
        (r"(?i)\bagreement\b|合同|协议|契约", 0.3),
        (r"(?i)\bparty\s+[AB]\b|甲方|乙方|丙方", 0.3),
        (r"(?i)\bwarrant(y|ies)\b|保证|担保", 0.2),
        (r"(?i)\btermination\b|合同终止|违约责任", 0.2),
        (r"(?i)\bconfidential\b|保密|机密", 0.2),
        (r"(?i)\bgoverning\s+law\b|管辖法律|适用法律", 0.3),
        (r"^\d{1,3}[\.\、]\d{1,3}[\.\、]", 0.2),  # 条款编号 1.1.1
        (r"(?i)\bhereby\b|herein|hereof|兹|特此|据此", 0.2),
    ]

    # 技术文档/手册特征
    _TECHNICAL_PATTERNS = [
        (r"(?i)\bapi\b|接口|端点", 0.25),
        (r"(?i)\binstall(ation)?\b|安装|部署|配置", 0.2),
        (r"(?i)\bgetting\s+started\b|快速开始|入门指南", 0.25),
        (r"(?i)\bexample(s)?\b|示例|范例", 0.15),
        (r"(?i)\bparameter(s)?\b|参数|返回值", 0.2),
        (r"(?i)\berror\s+code\b|错误码|异常处理", 0.2),
        (r"```|~~~|~~~", 0.3),  # 代码块标记
        (r"(?i)\bgit\s+clone\b|npm\s+install|pip\s+install|docker\s+run", 0.3),
        (r"(?i)\bfunction\b|\bclass\b|\bdef\b|\bimport\b|\bconst\b|\blet\b|\bvar\b", 0.15),
    ]

    # 报告/白皮书特征
    _REPORT_PATTERNS = [
        (r"(?i)\bexecutive\s+summary\b|执行摘要|内容摘要", 0.3),
        (r"(?i)\bfinding(s)?\b|调查发现|主要发现", 0.25),
        (r"(?i)\brecommendation(s)?\b|建议|对策建议", 0.25),
        (r"(?i)\bmarket\s+(analysis|size|trend)\b|市场分析|市场规模", 0.25),
        (r"(?i)\bwhitepaper\b|白皮书|行业报告|研究报告", 0.3),
        (r"(?i)\bforecast\b|预测|展望|趋势", 0.2),
        (r"(?i)\bcase\s+study\b|案例分析", 0.25),
    ]

    # Markdown 特有特征
    _MARKDOWN_PATTERNS = [
        (r"^#{1,6}\s+", 0.4),           # Markdown 标题
        (r"\[.*?\]\(.*?\)", 0.15),       # 链接
        (r"`[^`]+`|```[\s\S]*?```", 0.2),  # 内联/块级代码
        (r"^\s*[-*+]\s+", 0.1),          # 无序列表
        (r"^\s*\d+\.\s+", 0.1),          # 有序列表
        (r"\|.*\|.*\|[\s\S]*?\|[-|]+\|", 0.25),  # 表格
        (r"^>\s+", 0.1),                  # 引用
    ]

    def __init__(self) -> None:
        self._academic_re = [re.compile(p, re.MULTILINE) for p, _ in self._ACADEMIC_PATTERNS]
        self._legal_re = [re.compile(p, re.MULTILINE) for p, _ in self._LEGAL_PATTERNS]
        self._technical_re = [re.compile(p, re.MULTILINE) for p, _ in self._TECHNICAL_PATTERNS]
        self._report_re = [re.compile(p, re.MULTILINE) for p, _ in self._REPORT_PATTERNS]
        self._markdown_re = [re.compile(p, re.MULTILINE) for p, _ in self._MARKDOWN_PATTERNS]

    def analyze(
        self,
        full_text: str,
        structured_blocks: list[Any],  # list[StructuredBlock] (avoid circular import)
        page_count: int = 1,
        file_ext: str = "",
    ) -> DocStructure:
        """分析文档结构并返回推荐策略。"""

        # 1. 检测 Markdown
        if file_ext in (".md",) or self._score_text(full_text, self._markdown_re) > 0.3:
            return self._build_markdown_structure(full_text, structured_blocks, page_count)

        # 2. 检测文档大类
        scores: dict[DocCategory, float] = {}
        scores[DocCategory.ACADEMIC] = self._score_text(full_text, self._academic_re)
        scores[DocCategory.LEGAL] = self._score_text(full_text, self._legal_re)
        scores[DocCategory.TECHNICAL] = self._score_text(full_text, self._technical_re)
        scores[DocCategory.REPORT] = self._score_text(full_text, self._report_re)

        best_category = max(scores, key=lambda k: scores[k])
        best_score = scores[best_category]

        if best_score < 0.15:
            return self._build_general_structure(full_text, structured_blocks, page_count)

        return self._build_typed_structure(
            best_category, best_score, full_text, structured_blocks, page_count
        )

    def _score_text(self, text: str, patterns: list[re.Pattern[str]]) -> float:
        """对文本按模式打分，返回 0~1 的置信度。"""
        if not text:
            return 0.0
        # 每个类别取各自对应的 pattern+weight 列表
        pattern_weights = self._get_pattern_weights(patterns)
        total_weight = 0.0
        matched_weight = 0.0
        for pattern, weight in pattern_weights:
            total_weight += weight
            if re.search(pattern, text):
                matched_weight += weight

        if total_weight == 0:
            return 0.0
        return min(matched_weight / total_weight, 1.0)

    def _get_pattern_weights(self, patterns: list[re.Pattern[str]]) -> list[tuple[re.Pattern[str], float]]:
        """将编译后的正则列表映射回对应的权重。"""
        all_sets = [
            (self._academic_re, self._ACADEMIC_PATTERNS),
            (self._legal_re, self._LEGAL_PATTERNS),
            (self._technical_re, self._TECHNICAL_PATTERNS),
            (self._report_re, self._REPORT_PATTERNS),
            (self._markdown_re, self._MARKDOWN_PATTERNS),
        ]
        for compiled_list, source in all_sets:
            if compiled_list is patterns:
                return [(re.compile(p, re.MULTILINE), w) for p, w in source]
        # fallback
        return [(p, 0.1) for p in patterns]

    @staticmethod
    def _flatten_patterns() -> list[tuple[str, float]]:
        """扁平化所有模式列表。"""
        return (
            DocumentTypeAnalyzer._ACADEMIC_PATTERNS
            + DocumentTypeAnalyzer._LEGAL_PATTERNS
            + DocumentTypeAnalyzer._TECHNICAL_PATTERNS
            + DocumentTypeAnalyzer._REPORT_PATTERNS
        )

    def _extract_headings(self, full_text: str) -> list[HeadingNode]:
        """从纯文本中提取章节标题层级。"""
        headings: list[HeadingNode] = []
        # 匹配多种中文/英文标题格式
        heading_patterns: list[tuple[str, Callable[[re.Match[str]], tuple[int, str]]]] = [
            # Markdown style
            (r"^(#{1,6})\s+(.+?)(?:\s*\{#.*?\})?\s*$", lambda m: (len(m.group(1)), m.group(2).strip())),
            # 中文编号: 第一章 / 1. / 1.1 / 1.1.1
            (r"^(第[一二三四五六七八九十百千\d]+[章节篇部])\s*(.*)", lambda m: (1, f"{m.group(1)} {m.group(2)}".strip())),
            # 编号标题: 1. 标题 / 1.1 标题
            (r"^(\d+(?:\.\d+)*)\s+(.+)$", lambda m: (len(m.group(1).split(".")), m.group(2).strip())),
            # 中文括号编号: （一）/ (1)
            (r"^[（(][一二三四五六七八九十\d]+[）)]\s*(.*)", lambda m: (1, m.group(1).strip())),
        ]

        lines = full_text.split("\n")
        for line in lines:
            line = line.strip()
            if not line or len(line) > 200:
                continue
            for pattern, extractor in heading_patterns:
                m = re.match(pattern, line)
                if m:
                    level, title = extractor(m)
                    level = min(level, 6)
                    headings.append(HeadingNode(level=level, title=title))
                    break

        # 构建层级树
        return self._build_heading_tree(headings)

    def _build_heading_tree(self, flat_headings: list[HeadingNode]) -> list[HeadingNode]:
        """将扁平标题列表构建为层级树。"""
        if not flat_headings:
            return []

        root: list[HeadingNode] = []
        stack: list[HeadingNode] = []

        for h in flat_headings:
            # 弹出直到找到父级
            while stack and stack[-1].level >= h.level:
                stack.pop()

            if stack:
                stack[-1].children.append(h)
                h._parent = stack[-1]
            else:
                root.append(h)

            stack.append(h)

        return root

    def _count_content_types(self, blocks: list[Any]) -> dict[str, int]:
        """统计各内容类型数量。"""
        counts = {"text": 0, "table": 0, "image": 0}
        for block in blocks:
            block_type = getattr(block, "block_type", "text")
            counts[block_type] = counts.get(block_type, 0) + 1
        # count code blocks in text
        for block in blocks:
            if getattr(block, "block_type", "") == "text":
                content = getattr(block, "content", "")
                counts["code_block"] = counts.get("code_block", 0) + len(
                    re.findall(r"```[\s\S]*?```|~~~[\s\S]*?~~~", content)
                )
        return counts

    def _detect_language(self, text: str) -> str:
        """检测文本语言。"""
        chinese_chars = len(re.findall(r"[一-鿿㐀-䶿]", text))
        total_chars = len(text.replace(" ", "").replace("\n", ""))
        if total_chars == 0:
            return "unknown"
        cn_ratio = chinese_chars / total_chars
        if cn_ratio > 0.6:
            return "zh"
        elif cn_ratio < 0.3:
            return "en"
        return "mixed"

    # ---- Structure builders per category ----

    def _build_markdown_structure(
        self, full_text: str, blocks: list[Any], page_count: int
    ) -> DocStructure:
        headings = self._extract_headings(full_text)
        counts = self._count_content_types(blocks)
        return DocStructure(
            category=DocCategory.MARKDOWN,
            confidence=0.85,
            total_pages=page_count,
            headings=headings,
            text_ratio=0.8,
            table_count=counts.get("table", 0),
            image_count=counts.get("image", 0),
            code_block_count=counts.get("code_block", 0),
            detected_lang=self._detect_language(full_text),
            key_patterns=["markdown_heading", "code_block"],
            recommended_chunk_size=800,
            recommended_chunk_overlap=100,
            use_parent_chunking=True,
            preserve_table_context=True,
            merge_small_paragraphs=True,
        )

    def _build_general_structure(
        self, full_text: str, blocks: list[Any], page_count: int
    ) -> DocStructure:
        counts = self._count_content_types(blocks)
        return DocStructure(
            category=DocCategory.GENERAL,
            confidence=0.5,
            total_pages=page_count,
            headings=[],
            text_ratio=0.9,
            table_count=counts.get("table", 0),
            image_count=counts.get("image", 0),
            code_block_count=counts.get("code_block", 0),
            detected_lang=self._detect_language(full_text),
            key_patterns=[],
            recommended_chunk_size=500,
            recommended_chunk_overlap=50,
            use_parent_chunking=True,
            preserve_table_context=True,
            merge_small_paragraphs=True,
        )

    def _build_typed_structure(
        self,
        category: DocCategory,
        confidence: float,
        full_text: str,
        blocks: list[Any],
        page_count: int,
    ) -> DocStructure:
        headings = self._extract_headings(full_text)
        counts = self._count_content_types(blocks)

        # 不同类型推荐不同分块策略
        strategy_map = {
            DocCategory.ACADEMIC: (800, 100, True),
            DocCategory.LEGAL: (300, 30, False),   # 法律文档小分块 + 精确匹配
            DocCategory.TECHNICAL: (1000, 150, True),  # 技术文档大段
            DocCategory.REPORT: (600, 80, True),
        }
        chunk_size, chunk_overlap, use_parent = strategy_map.get(
            category, (500, 50, False)
        )

        return DocStructure(
            category=category,
            confidence=confidence,
            total_pages=page_count,
            headings=headings,
            text_ratio=counts.get("text", 0) / max(sum(counts.values()), 1),
            table_count=counts.get("table", 0),
            image_count=counts.get("image", 0),
            code_block_count=counts.get("code_block", 0),
            detected_lang=self._detect_language(full_text),
            key_patterns=[],
            recommended_chunk_size=chunk_size,
            recommended_chunk_overlap=chunk_overlap,
            use_parent_chunking=use_parent,
            preserve_table_context=True,
            merge_small_paragraphs=category != DocCategory.LEGAL,
            extra_metadata={
                "category_label": {
                    DocCategory.ACADEMIC: "学术论文",
                    DocCategory.LEGAL: "法律/合同",
                    DocCategory.TECHNICAL: "技术文档",
                    DocCategory.REPORT: "报告/白皮书",
                }.get(category, "通用"),
            },
        )
