"""
参考文献提取器 —— 从参考文献文本块中解析出逐条结构化引用条目。

支持格式：
- 编号引用：[1] Author. Title. Journal, Year.
- 中文引用：[1] 作者. 标题[J]. 期刊，年份.
- 作者-年份：(Smith et al., 2020)
- DOI 提取
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ReferenceEntry:
    """单条参考文献的结构化表示。"""

    ref_id: str  # 引用编号 或 chunk_id
    raw_text: str  # 原始文本
    authors: str | None = None
    title: str | None = None
    year: str | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    ref_type: str = "unknown"  # journal | book | conference | thesis | web | patent | standard

    @property
    def short_citation(self) -> str:
        """生成简短引用文本（作者, 年份）。"""
        parts = []
        if self.authors:
            first_author = self.authors.split(",")[0].split(";")[0].strip()
            et_al = "等" if ";" in self.authors or "，" in self.authors else ""
            parts.append(f"{first_author}{et_al}")
        if self.year:
            parts.append(f"({self.year})")
        return " ".join(parts) if parts else self.raw_text[:80]


# ── 解析规则 ──────────────────────────────────────────────

# 编号引用前缀匹配：中英文各种变体
#   [1] [1]. [1], (1) [1]Smith [ 1 ] [1] Author 1. 1)  [1]Zhang
# 分隔符改为 *（零或多次），兼容 [1]Smith / [1]Zhang 等紧凑格式
_RE_NUMBERED_PREFIX = re.compile(
    r"^\s*[\[\(（]?\s*(\d+)\s*[\]\)）]?\s*[\.\s、．,，;；:：]*\s*"
)

# 同行拆分用：匹配编号引用开头（使用 lookbehind 不消费前导标点）
_RE_NUMBERED_ANYWHERE = re.compile(
    r"(?:^|(?<=[\n。.!?！？])|(?<=[^0-9]))"
    r"\s*[\[\(（]?\s*(\d+)\s*[\]\)）]?\s*"
    r"(?=[A-Z一-鿿぀-ゟ゠-ヿ])",
    re.MULTILINE,
)

# DOI 模式
_RE_DOI = re.compile(
    r"\b(10\.\d{4,}(?:\.\d+)*\/\S+)\b",
    re.IGNORECASE,
)

# URL 模式
_RE_URL = re.compile(
    r"https?://[^\s\]）)]+",
    re.IGNORECASE,
)

# 年份提取
_RE_YEAR = re.compile(r"[\[（(]?\b(19\d{2}|20\d{2})[\]）)]?\b")

# 中文作者模式: 作者1，作者2，作者3. 或 Author1, Author2, and Author3.
_RE_CHINESE_AUTHORS = re.compile(
    r"^([^.!?。！？\n]{0,200}?)[\.。]?\s*(.{0,100}?)\s*[\[（(][JCDMPSNWBRT][\]）)]",
    re.MULTILINE,
)

# 英文作者模式: Lastname, F., Lastname2, F., ...
_RE_ENG_AUTHORS = re.compile(
    r"^([A-Z][a-z]+(?:-[A-Z][a-z]+)?,\s*[A-Z]\.(?:,?\s*[A-Z][a-z]+(?:-[A-Z][a-z]+)?,\s*[A-Z]\.)*)",
)

# 期刊类型标记: [J], [C], [D], [M], etc.
_RE_REF_TYPE = re.compile(r"[\[（(]([JCDMPSNWBRT])[\]）)]", re.IGNORECASE)

_REF_TYPE_MAP: dict[str, str] = {
    "J": "journal",
    "C": "conference",
    "D": "thesis",
    "M": "book",
    "P": "patent",
    "S": "standard",
    "N": "newspaper",
    "W": "web",
    "B": "book",
    "R": "report",
    "T": "patent",
}


class ReferenceExtractor:
    """参考文献解析器。"""

    # 参考文献 section 的标题关键词
    SECTION_KEYWORDS: list[str] = [
        "参考文献", "references", "bibliography",
        "引用文献", "参考书目", "works cited",
    ]

    @classmethod
    def is_reference_section(cls, title: str | None) -> bool:
        """判断给定的章节标题是否为参考文献 section。"""
        if not title:
            return False
        lower = title.strip().lower()
        return any(kw in lower for kw in cls.SECTION_KEYWORDS)

    @classmethod
    def extract_entries(cls, text: str) -> list[ReferenceEntry]:
        """从参考文献文本中提取逐条引用条目。"""
        if not text.strip():
            return []

        # 尝试按编号拆分
        entries = cls._split_numbered(text)
        # 拆太少且文本长 → 同行密集排列，用贪婪正则再拆
        if len(entries) <= 2 and len(text) > 150:
            entries = cls._split_by_regex_greedy(text)
        # 仍然无编号 → 按空行拆分兜底
        if len(entries) <= 1:
            entries = cls._split_by_blank_lines(text)

        # 解析每条
        results: list[ReferenceEntry] = []
        for i, entry_text in enumerate(entries):
            text_clean = entry_text.strip()
            if not text_clean or len(text_clean) < 5:
                continue

            ref_id = str(i + 1)
            doi_match = _RE_DOI.search(text_clean)
            url_match = _RE_URL.search(text_clean)
            year_match = _RE_YEAR.search(text_clean)
            type_match = _RE_REF_TYPE.search(text_clean)

            # 尝试提取作者和标题
            authors, title = cls._extract_authors_title(text_clean)

            results.append(ReferenceEntry(
                ref_id=ref_id,
                raw_text=text_clean,
                authors=authors,
                title=title,
                year=year_match.group(1) if year_match else None,
                doi=doi_match.group(1) if doi_match else None,
                url=url_match.group(0) if url_match else None,
                ref_type=_REF_TYPE_MAP.get(
                    type_match.group(1).upper(), "unknown",
                ) if type_match else "unknown",
            ))

        return results

    @classmethod
    def _split_numbered(cls, text: str) -> list[str]:
        """按编号前缀拆分参考文献块，同时处理跨行和同行两种布局。

        策略：
        1. 按行首编号拆分（最常见：每行以 [1] 开头）
        2. 同行多个引用条目时，用全文正则再拆一次
        """
        lines = text.split("\n")
        groups: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if _RE_NUMBERED_PREFIX.match(line):
                if current:
                    groups.append(current)
                current = [line]
            else:
                current.append(line)

        if current:
            groups.append(current)

        # 合并每组 → 逐条句子
        entries = [" ".join(g) for g in groups]

        # 如果只拆出 1-2 条但文本够长（>150字），说明是同行密集排列
        # 用全文正则 _RE_NUMBERED_ANYWHERE 再次拆分
        if len(entries) <= 2:
            full_text = " ".join(entries)
            if len(full_text) > 150:
                entries = cls._split_by_regex_greedy(full_text)

        return entries

    @classmethod
    def _split_by_regex_greedy(cls, text: str) -> list[str]:
        """按编号正则贪婪拆分整段文本（处理同行密集引用排列）。

        使用 _RE_NUMBERED_ANYWHERE 找到每个编号位置，切出逐条引用。
        """
        matches = list(_RE_NUMBERED_ANYWHERE.finditer(text))
        if len(matches) <= 1:
            return [text] if text.strip() else []

        entries: list[str] = []
        for i, m in enumerate(matches):
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            entry = text[start:end].strip()
            if entry and len(entry) >= 5:
                entries.append(entry)
        return entries

    @staticmethod
    def _split_by_blank_lines(text: str) -> list[str]:
        """按空行拆分参考文献。"""
        parts = re.split(r"\n\s*\n", text)
        return [p.strip() for p in parts if p.strip()]

    @classmethod
    def _extract_authors_title(cls, entry: str) -> tuple[str | None, str | None]:
        """从条目中提取作者和标题。"""
        authors = None
        title = None

        # 尝试英文格式: Lastname, F., ...
        eng_match = _RE_ENG_AUTHORS.match(entry)
        if eng_match:
            authors = eng_match.group(1).strip().rstrip(",")
            remaining = entry[eng_match.end():].strip()
            # 提取标题：作者之后到期刊标记/年份之前
            title_end = re.search(r"[\[（(][JCDMPSNWBRT][\]）)]|\b(19|20)\d{2}\b", remaining)
            if title_end:
                title = remaining[:title_end.start()].strip().strip(".。")
            else:
                title = remaining[:150].strip().strip(".。")
            return authors, title

        # 尝试中文格式: 作者. 标题[J]. ...
        cn_match = _RE_CHINESE_AUTHORS.match(entry)
        if cn_match:
            authors = cn_match.group(1).strip().strip(".。，,")
            title = cn_match.group(2).strip().strip(".。")
            return authors, title

        return authors, title
