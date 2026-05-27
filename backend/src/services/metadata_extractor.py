"""
文档元数据深度提取器。

从解析后的 StructuredBlock 列表中自动提取：
- DOI（Digital Object Identifier）
- 摘要（Abstract / 摘要）
- 关键词（Keywords / 关键词）
- 作者信息
- 发表日期
- 文档类型标识（J/C/D/M/P 等期刊/会议/学位论文标记）
- 期刊/会议名称
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from src.services.chunking_service import StructuredBlock


@dataclass
class DocumentMetadata:
    """结构化文档元数据。"""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    doi: str | None = None
    abstract: str | None = None
    keywords: list[str] = field(default_factory=list)
    publication_date: str | None = None
    journal: str | None = None
    doc_type: str | None = None  # journal / conference / thesis / book / report / patent
    language: str | None = None

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "authors": self.authors,
            "doi": self.doi,
            "abstract": self.abstract,
            "keywords": self.keywords,
            "publication_date": self.publication_date,
            "journal": self.journal,
            "doc_type": self.doc_type,
            "language": self.language,
        }


# ── 正则模式 ──────────────────────────────────────────────────

# DOI: 10.XXXX/XXXX...
_DOI_RE = re.compile(
    r"\b(10\.\d{4,}(?:\.\d+)*\/\S+)\b",
    re.IGNORECASE,
)

# 摘要标题
_ABSTRACT_START_CN = re.compile(
    r"^(?:摘要|内容提要|概要)[：:\s]*",
)
_ABSTRACT_START_EN = re.compile(
    r"^(?:Abstract|Summary|ABSTRACT)[：:\s]*",
    re.IGNORECASE,
)

# 关键词标题
_KEYWORDS_START_CN = re.compile(
    r"^(?:关键词|关键字)[：:\s]+",
)
_KEYWORDS_START_EN = re.compile(
    r"^(?:Keywords?|Key\s+Words?)[：:\s]+",
    re.IGNORECASE,
)

# 作者信息（中英文）
_AUTHORS_CN = re.compile(
    r"^(?:作者|Authors?)[：:\s]+(.{5,200})$",
    re.IGNORECASE | re.MULTILINE,
)

# 英文学术作者格式: First Last, First2 Last2, ...
_AUTHORS_EN_LINE = re.compile(
    r"^([A-Z][a-zà-ü]+(?:\s+[A-Z]\.)+"
    r"(?:,\s*[A-Z][a-zà-ü]+(?:\s+[A-Z]\.)+)*)",
    re.MULTILINE,
)

# 中文作者: 张三，李四，王五
_AUTHORS_CN_LINE = re.compile(
    r"([一-鿿]{2,4}(?:[，,]\s*[一-鿿]{2,4}){1,10})",
)

# 发表日期
_DATE_CN = re.compile(
    r"(?:发表|出版|投稿|录用|在线出版)?日期[：:\s]*(\d{4}[-年]\d{1,2}[-月]\d{1,2}[日]?)",
)
_DATE_EN = re.compile(
    r"(?:Published|Date|Received)[：:\s]*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
    re.IGNORECASE,
)

# 期刊/会议名
_JOURNAL_CN = re.compile(
    r"(?:期刊|杂志|学报)[：:\s]*[《「]([^》」]{2,80})[》」]",
)
_JOURNAL_EN = re.compile(
    r"(?:Journal\s+of\s+|Proceedings\s+of\s+|Conference\s+on\s+)",
    re.IGNORECASE,
)

# 中文学位论文
_THESIS_CN = re.compile(
    r"(?:硕士|博士|学士)学位论文",
)

# 文档类型标记 [J] [C] [D] [M] [P] [S] [N] [R]
_REF_TYPE_MARKER = re.compile(r"[\[（(]([JCDMPSNRBT])[\]）)]")

_REF_TYPE_MAP: dict[str, str] = {
    "J": "journal",
    "C": "conference",
    "D": "thesis",
    "M": "book",
    "P": "patent",
    "S": "standard",
    "N": "newspaper",
    "R": "report",
    "B": "book",
    "T": "patent",
}


class MetadataExtractor:
    """从文档内容块中提取结构化元数据。"""

    # 搜索范围：前 N 页（元数据通常在文档开头）
    _SEARCH_PAGES = 5

    @classmethod
    def extract(
        cls,
        blocks: list[StructuredBlock],
        page_count: int = 0,
        ext: str = "",
    ) -> DocumentMetadata:
        """从解析后的块列表中提取元数据。"""
        meta = DocumentMetadata()

        # 收集前几页文本
        search_pages = min(cls._SEARCH_PAGES, max(page_count, 1))
        full_text = cls._collect_search_text(blocks, search_pages)

        if not full_text:
            return meta

        # 1. DOI
        doi_match = _DOI_RE.search(full_text)
        if doi_match:
            meta.doi = doi_match.group(1)

        # 2. 摘要
        meta.abstract = cls._extract_abstract(full_text)

        # 3. 关键词
        meta.keywords = cls._extract_keywords(full_text)

        # 4. 作者
        meta.authors = cls._extract_authors(full_text)

        # 5. 发表日期
        meta.publication_date = cls._extract_date(full_text)

        # 6. 文档类型
        meta.doc_type = cls._extract_doc_type(full_text, ext)

        # 7. 期刊/会议名
        meta.journal = cls._extract_journal(full_text)

        # 8. 语言检测
        meta.language = cls._detect_language(full_text)

        logger.info(
            f"元数据提取: doi={meta.doi is not None}, "
            f"abstract={len(meta.abstract or '')}chars, "
            f"keywords={len(meta.keywords)}, "
            f"authors={len(meta.authors)}, "
            f"type={meta.doc_type}, "
            f"lang={meta.language}"
        )

        return meta

    @staticmethod
    def _collect_search_text(
        blocks: list[StructuredBlock], max_pages: int
    ) -> str:
        """收集前 N 页的文本内容（含表格文本）。"""
        parts: list[str] = []
        for block in blocks:
            if block.page_number > max_pages:
                break
            if block.block_type == "text":
                parts.append(block.content)
            elif block.block_type == "table" and block.table_data:
                # 包括表格标题和数据
                if block.table_caption:
                    parts.append(block.table_caption)
                for row in block.table_data:
                    parts.append(" ".join(str(c) for c in row if c))
        return "\n".join(parts)

    @classmethod
    def _extract_abstract(cls, text: str) -> str | None:
        """提取摘要段落。"""
        # 尝试中文摘要
        lines = text.split("\n")
        in_abstract = False
        abstract_lines: list[str] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_abstract and abstract_lines:
                    break  # 空行结束摘要
                continue

            if in_abstract:
                # 遇到下一章节标题则停止
                if cls._is_section_boundary(stripped):
                    break
                if len(stripped) > 5:
                    abstract_lines.append(stripped)
            elif _ABSTRACT_START_CN.match(stripped) or _ABSTRACT_START_EN.match(stripped):
                in_abstract = True
                # 摘要标题后的内容可能在同一行
                after_title = _ABSTRACT_START_CN.sub("", stripped)
                after_title = _ABSTRACT_START_EN.sub("", after_title)
                if after_title.strip():
                    abstract_lines.append(after_title.strip())

        if abstract_lines:
            result = " ".join(abstract_lines)
            return result[:3000]  # 限制长度
        return None

    @classmethod
    def _extract_keywords(cls, text: str) -> list[str]:
        """提取关键词列表。"""
        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            # 中文关键词
            if _KEYWORDS_START_CN.match(stripped):
                kw_text = _KEYWORDS_START_CN.sub("", stripped)
                return cls._split_keywords(kw_text)
            # 英文关键词
            if _KEYWORDS_START_EN.match(stripped):
                kw_text = _KEYWORDS_START_EN.sub("", stripped)
                return cls._split_keywords(kw_text)
        return []

    @staticmethod
    def _split_keywords(text: str) -> list[str]:
        """拆分关键词字符串，优先按主要分隔符拆分，保留英文短语完整性。"""
        # 1. 先按主要分隔符拆分（；; ，，）
        parts = re.split(r"[;；,，、]", text)
        # 2. 清洗每个部分
        result: list[str] = []
        for p in parts:
            p = p.strip().rstrip(".").rstrip("。")
            # 对于英文关键词，额外合并过短的片段（被空格误拆的）
            if len(p) > 1:
                result.append(p)
        # 3. 后处理：如果关键词有纯空格分隔的英文子词，尝试合并
        # 但中文关键词不应合并
        merged: list[str] = []
        i = 0
        while i < len(result):
            kw = result[i]
            # 如果当前词是纯 ASCII 短词且下文有更多短词 → 可能是被空格拆开的英文短语
            if kw.isascii() and len(kw.split()) == 1 and i + 1 < len(result):
                next_kw = result[i + 1]
                if next_kw.isascii() and len(next_kw.split()) == 1:
                    merged.append(f"{kw} {next_kw}")
                    i += 2
                    continue
            merged.append(kw)
            i += 1
        return merged

    @classmethod
    def _extract_authors(cls, text: str) -> list[str]:
        """提取作者列表。"""
        # 尝试"作者："标注行
        for line in text.split("\n"):
            line = line.strip()
            m = _AUTHORS_CN.match(line)
            if m:
                authors_text = m.group(1)
                return [a.strip() for a in re.split(r"[;；,，]", authors_text) if a.strip()]

        # 尝试英文标准格式: 多个 Lastname, F. 行
        # 在文本前 1000 字符内搜索
        search = text[:2000]
        for match in _AUTHORS_EN_LINE.finditer(search):
            authors_text = match.group(0)
            if len(authors_text) > 15:  # 足够长才像作者列表
                return [a.strip() for a in authors_text.split(",") if a.strip()]

        # 尝试中文作者行
        for match in _AUTHORS_CN_LINE.finditer(search):
            authors_text = match.group(0)
            if len(authors_text) > 5 and "。" not in authors_text:
                return [a.strip() for a in re.split(r"[，,]", authors_text) if a.strip()]

        return []

    @classmethod
    def _extract_date(cls, text: str) -> str | None:
        """提取发表日期。"""
        for line in text.split("\n"):
            m = _DATE_CN.search(line)
            if m:
                return m.group(1)
            m = _DATE_EN.search(line)
            if m:
                return m.group(1)

        # 回退：搜索文本中 ISO 日期
        iso_match = re.search(r"\b(20\d{2}[-/]\d{2}[-/]\d{2})\b", text[:2000])
        if iso_match:
            return iso_match.group(1)
        return None

    @classmethod
    def _extract_doc_type(cls, text: str, ext: str) -> str | None:
        """推断文档类型。"""
        # 1. 参考文献格式标记 [J]/[C]/[D] 等
        markers = _REF_TYPE_MARKER.findall(text[:3000])
        if markers:
            # 取最常见的标记
            from collections import Counter
            most_common = Counter(markers).most_common(1)[0][0].upper()
            return _REF_TYPE_MAP.get(most_common)

        # 2. 学位论文关键词
        if _THESIS_CN.search(text[:3000]):
            return "thesis"

        # 3. 专利标记
        if re.search(r"(?:专利号|Patent\s*No\.|申请号)", text[:2000]):
            return "patent"

        # 4. 技术标准
        if re.search(r"(?:GB/T|ISO\s*\d|标准编号|Standard)", text[:2000]):
            return "standard"

        return None

    @classmethod
    def _extract_journal(cls, text: str) -> str | None:
        """提取期刊/会议名称。"""
        # 中文期刊
        m = _JOURNAL_CN.search(text[:3000])
        if m:
            return m.group(1).strip()

        # 英文期刊/会议
        for match in _JOURNAL_EN.finditer(text[:3000]):
            # 提取完整名称（取整行）
            start = max(0, match.start() - 20)
            end = min(len(text), match.end() + 100)
            context = text[start:end]
            name_match = re.search(
                r"(?:Journal\s+of\s+\w+|Proceedings\s+of\s+[\w\s]+|"
                r"Conference\s+on\s+[\w\s]+)",
                context,
                re.IGNORECASE,
            )
            if name_match:
                journal = name_match.group(0).strip()
                # 截断到合适长度
                if len(journal) > 120:
                    journal = journal[:120] + "..."
                return journal

        return None

    @classmethod
    def _detect_language(cls, text: str) -> str:
        """检测文档主要语言。"""
        sample = text[:2000]
        cjk_chars = len(re.findall(r"[一-鿿]", sample))
        total = len(sample)
        if total == 0:
            return "unknown"
        cjk_ratio = cjk_chars / total

        if cjk_ratio > 0.15:
            return "zh"
        if cjk_ratio > 0.02:
            return "mixed"
        return "en"

    @staticmethod
    def _is_section_boundary(line: str) -> bool:
        """判断是否为新章节边界（摘要应在此停止）。"""
        section_patterns = [
            r"^(?:#{1,6}\s+)",
            r"^(?:第[一二三四五六七八九十百千\d]+[章节篇部条])",
            r"^\d+\.\s+[A-Z一-鿿]",  # "1. 引言" 格式
            r"^\d+(?:\.\d+)*\s+[A-Z一-鿿]",  # "1.1 概述" 格式
            r"^(?:Introduction|Method|Experiment|Result|Conclusion|Reference)",
            r"^(?:引言|方法论|实验|结果|结论|参考文献)",
            r"^(?:关键词|关键字|Keywords?)[：:\s]",
            r"^(?:作者|Authors?)[：:\s]",
        ]
        for pattern in section_patterns:
            if re.match(pattern, line, re.IGNORECASE):
                return True
        return False
