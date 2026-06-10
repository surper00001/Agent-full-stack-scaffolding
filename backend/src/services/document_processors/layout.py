"""
版面分析与阅读顺序恢复 —— PDF/DOCX 通用语义结构重建。

PDF 本质上是一张"画布"，而非文档。此模块负责将画布上的视觉元素
还原为人类阅读时的语义结构：

  PDF 页 → 字体分析 → 位置分类 → 阅读顺序 → 语义标签

管线：
  1. FontAnalysis    — 提取字体大小/粗细/族信息，建立页面字体层级
  2. RegionClassify  — 按位置将区域分为：正文/页眉/页脚/侧栏
  3. BlockTag        — 综合字体+位置+内容，为每个块打语义标签
  4. ReadingOrder    — 检测多栏布局，恢复正确的阅读顺序
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from src.services.chunking.data_models import StructuredBlock


class LayoutTag(StrEnum):
    """块的语义角色标签——对应人类阅读时的认知分类。"""

    TITLE = "title"            # 文档标题（最大字号）
    HEADING = "heading"        # 章节标题
    SUBTITLE = "subtitle"      # 副标题/二级标题
    BODY = "body"              # 正文段落
    ABSTRACT = "abstract"      # 摘要
    KEYWORDS = "keywords"      # 关键词
    CAPTION = "caption"        # 图表标题/说明
    HEADER = "header"          # 页眉（重复出现）
    FOOTER = "footer"          # 页脚（页码等）
    FOOTNOTE = "footnote"      # 脚注
    REFERENCE = "reference"    # 参考文献条目
    FORMULA = "formula"        # 行间/行内公式
    LIST_ITEM = "list_item"    # 列表项
    TABLE_BODY = "table_body"  # 表格内容（与 block_type 正交）
    IMAGE_REGION = "image"     # 图片区域
    CODE = "code"              # 代码块
    TEMPLATE_NOISE = "template_noise"  # 跨页重复的模板噪声（水印、重复警告语等）


# ── 字体描述 ──────────────────────────────────────────────


@dataclass
class FontInfo:
    """从 PyMuPDF / DOCX 提取的字体信息。"""

    size: float               # 字号（pt）
    bold: bool = False
    italic: bool = False
    font_name: str = ""       # 字体族名，如 "SimHei", "Times New Roman"
    color: tuple[float, ...] = (0, 0, 0)

    @property
    def is_serif(self) -> bool:
        return any(s in self.font_name.lower() for s in ("times", "song", "songti", "simsun", "宋体"))

    @property
    def is_sans(self) -> bool:
        return any(s in self.font_name.lower() for s in ("arial", "helvetica", "hei", "heiti", "simhei", "黑体", "microsoft yahei"))


@dataclass
class PageFontProfile:
    """单页字体层级画像——用于识别标题/正文的字号分界线。"""

    page_num: int
    fonts: list[FontInfo] = field(default_factory=list)
    body_size: float = 10.0      # 正文字号（众数）
    title_size: float = 14.0     # 最小标题字号（>body_size 的第一个波峰）
    max_size: float = 10.0

    @property
    def heading_threshold(self) -> float:
        """超过此字号的文本被认为是标题。"""
        return self.body_size + 1.5


# ── 版面区域分类 ──────────────────────────────────────────


class Region:
    """页面区域分类器——按视觉位置将页面划分为功能区域。"""

    # 页眉/页脚比例阈值
    HEADER_RATIO = 0.12          # 页面顶部 12% 为页眉区
    FOOTER_RATIO = 0.12          # 页面底部 12% 为页脚区
    SIDEBAR_WIDTH_RATIO = 0.25   # 宽度 <25% 的列视为侧栏

    @classmethod
    def classify(cls, page_width: float, page_height: float, bbox: tuple[float, float, float, float]) -> str:
        """根据 bbox 在页面中的位置，返回区域类型。"""
        x0, y0, x1, y1 = bbox
        block_width = x1 - x0
        block_height = y1 - y0

        if block_width <= 0 or block_height <= 0:
            return "invalid"

        # 页眉：顶部
        if y1 <= page_height * cls.HEADER_RATIO:
            return "header_zone"

        # 页脚：底部
        if y0 >= page_height * (1 - cls.FOOTER_RATIO):
            return "footer_zone"

        # 侧栏：极窄
        if block_width < page_width * cls.SIDEBAR_WIDTH_RATIO and (x0 < page_width * 0.15 or x1 > page_width * 0.85):
            return "sidebar"

        # 主内容区
        return "body_zone"


# ── 页眉/页脚内容白名单 ────────────────────────────────────

# 已知的页眉/页脚噪声模式（全文档重复出现）
_HEADER_FOOTER_NOISE_RE = re.compile(
    r"^\s*(\d{1,4}\s*$"  # 纯页码
    r"|第\s*\d+\s*页\s*$"  # 第X页
    r"|Page\s+\d+\s*(of\s+\d+)?\s*$"  # Page X of Y
    r"|^\s*[©®™]\s*(19|20)\d{2}\s*"  # 版权信息
    r"|^\s*https?://"  # URL 脚注
    r"|^\s*Confidential\s*$"  # 保密标记
    r"|^\s*DRAFT\s*$"
    r"|^\s*[Vv]ersion\s*[\d.]+\s*$"  # 版本号
    r")",
    re.IGNORECASE,
)

# 已知的内容标题模式（即使位于页眉/页脚区域也不应去除）
_CONTENT_TITLE_WHITELIST = re.compile(
    r"^(#{1,6}\s+|"  # Markdown 标题
    r"第[一二三四五六七八九十百千\d]+[章节篇部条款]"  # 中文数字章节
    r"|\d+(?:\.\d+)*\s+[A-Z一-鿿]"  # 编号标题
    r"|(?:Abstract|Introduction|Method|Experiment|Result|Conclusion|Reference|Discussion|"
    r"Acknowledgment|Appendix|Summary|Background|Related\s+Work)\s*$"
    r"|[（(][一二三四五六七八九十\d]+[）)]"  # (一) 格式
    r")",
    re.IGNORECASE,
)


def is_likely_noise_in_header_footer(text: str, page_num: int) -> bool:
    """判断页眉/页脚区域内的文本是否为噪声（可安全去除）。

    白名单保护：
    - 章节/标题模式的内容 → 保留（返回 False）
    - 长句(>40字符) → 保留（返回 False）
    - 匹配已知噪声模式 → 去除（返回 True）

    用于在 filter_noise_blocks 之前做二次验证，避免误删正文标题。
    """
    stripped = text.strip()
    if not stripped:
        return True  # 空文本视为噪声

    # 白名单：看起来像标题 → 保留
    if _CONTENT_TITLE_WHITELIST.match(stripped):
        return False

    # 白名单：长句子（>40 字符）→ 很可能是正文，保留
    if len(stripped) > 40:
        return False

    # 白名单：包含中文句末标点 → 完整句子，保留
    if re.search(r"[。！？；]", stripped) and len(stripped) > 10:
        return False

    # 白名单：页码但有多余内容（如 "42 / 结论"）→ 保留
    if re.match(r"^\d{1,4}\s*/\s*\S{2,}", stripped):
        return False

    # 噪声模式：纯页码 / 页眉标题等
    if _HEADER_FOOTER_NOISE_RE.match(stripped):
        return True

    # 保守策略：短文本（≤20 字符）在页眉/页脚区域 → 噪声
    return bool(len(stripped) <= 20 and page_num > 1)


# ── 语义标签分配 ──────────────────────────────────────────


class BlockTagger:
    """为内容块分配语义标签（LayoutTag）。

    基于三类信息：
    1. 字体层级（字号/粗细）→ 标题 vs 正文
    2. 页面位置 → 页眉/页脚/侧栏
    3. 文本内容模式 → 参考文献/列表/摘要/关键词

    Reference detection handles:
      - English: [1] Smith, J., ...  or  Smith, J. (2020) ...
      - Chinese: [1] 张三，李四. ...  or  张三, 李四. 标题[J]. ...
      - DOI links, ibid/et al/等人 markers
      - Small-font text in late pages (typical of paper references)
    """

    # 参考文献条目开头模式
    _REF_ENTRY_START = re.compile(
        r"^\[\d+\]|"                         # [1], [12]
        r"^\d+\.\s*\[|"                      # 1. [
        r"^(?:[A-Z][a-zà-ü]+,\s+[A-Z]\.)|"   # Smith, J.
        r"^[A-Z][a-zà-ü]+(?:\s+[A-Z]\.)+|"   # Smith J. A.
        r"^[A-Z][A-Za-z\s\-]+\(?\d{4}[\)a-z]|"  # Smith (2020) or Smith 2020
        r"DOI[：:]\s*10\.|"                   # DOI: 10.xxx
        r"^(?:ibid|et al\.?|等人|同前|同上)",   # continuation markers
    )
    # 中文参考文献模式（方括号编号 + 中文人名）
    _REF_CHINESE_ENTRY = re.compile(
        r"^\[\d+\]\s*[一-鿿]|"       # [1] 张三...
        r"^\d+[\.\、\)）]\s*[一-鿿]",  # 1. 张三...
    )
    # 参考文献章节标题
    _REF_HEADING = re.compile(
        r"^(?:参考文献|References?|Bibliography|参考书目|引用文献|"
        r"Works\s+Cited|Reference\s+List)\s*$",
        re.IGNORECASE,
    )
    _KEYWORD_PATTERN = re.compile(
        r"^(?:关键词|关键字|Keywords?)[：:\s]",
        re.IGNORECASE,
    )
    _ABSTRACT_PATTERN = re.compile(
        r"^(?:摘要|Abstract|内容提要)",
        re.IGNORECASE,
    )
    _LIST_PATTERN = re.compile(
        r"^[\s]*(?:[-*+•·▪▸►➤]|\d+[\.\、\)]|[（(][\d一二三四五六七八九十]+[）)])",
    )
    _CAPTION_PATTERN = re.compile(
        r"^(?:图|Fig\.?|Figure|表|Tab\.?|Table)\s*\d+",
        re.IGNORECASE,
    )
    _FOOTNOTE_PATTERN = re.compile(
        r"^[\*†‡§¶#]|^\d{1,2}\)\s|^[①②③④⑤⑥⑦⑧⑨⑩]",
    )

    @classmethod
    def tag_text_block(
        cls,
        text: str,
        font: FontInfo | None,
        page_width: float,
        page_height: float,
        bbox: tuple[float, float, float, float] | None,
        *,
        body_font_size: float | None = None,
        page_num: int = 0,
        total_pages: int = 0,
    ) -> LayoutTag:
        """为一个文本块分配语义标签。

        Args:
            body_font_size: 文档正文字号（用于识别小字参考文献）
            page_num: 当前页码
            total_pages: 文档总页数（用于判断是否为文末参考文献区域）
        """
        if not text.strip():
            return LayoutTag.BODY

        stripped = text.strip()
        text_len = len(stripped)

        # 先按位置归区（带内容白名单保护，避免误删正文标题）
        if bbox:
            zone = Region.classify(page_width, page_height, bbox)
            if zone == "header_zone":
                if not is_likely_noise_in_header_footer(stripped, page_num):
                    pass  # 白名单内容：可能是章节标题，不标记为页眉
                else:
                    return LayoutTag.HEADER
            elif zone == "footer_zone":
                if not is_likely_noise_in_header_footer(stripped, page_num):
                    pass  # 白名单内容
                else:
                    return LayoutTag.FOOTER

        # 参考文献章节标题（如 "参考文献"、"References"）
        if cls._REF_HEADING.match(stripped) and text_len < 60:
            return LayoutTag.HEADING

        # 按内容模式
        if cls._KEYWORD_PATTERN.match(stripped):
            return LayoutTag.KEYWORDS
        if cls._ABSTRACT_PATTERN.match(stripped):
            return LayoutTag.ABSTRACT
        if cls._CAPTION_PATTERN.match(stripped):
            return LayoutTag.CAPTION

        # 参考文献检测（多策略）
        ref_score = cls._reference_score(stripped, text_len, font, body_font_size, page_num, total_pages)
        if ref_score >= 2:
            return LayoutTag.REFERENCE

        if cls._FOOTNOTE_PATTERN.match(stripped) and text_len < 200:
            return LayoutTag.FOOTNOTE
        if cls._LIST_PATTERN.match(stripped) and text_len < 300:
            return LayoutTag.LIST_ITEM

        # 按字体
        if font:
            if font.bold and font.size > 12 and text_len < 150:
                return LayoutTag.HEADING
            if font.size > 16:
                return LayoutTag.TITLE
            if font.bold and text_len < 120:
                return LayoutTag.HEADING
            if font.size > 12 and text_len < 120:
                return LayoutTag.SUBTITLE

        return LayoutTag.BODY

    @classmethod
    def _reference_score(
        cls,
        text: str,
        text_len: int,
        font: FontInfo | None,
        body_font_size: float | None,
        page_num: int,
        total_pages: int,
    ) -> int:
        """综合评分判断文本块是否为参考文献条目。

        返回值 >= 2 即判定为 REFERENCE。
        """
        score = 0

        # 1. 开头匹配参考文献条目模式
        if cls._REF_ENTRY_START.match(text) or cls._REF_CHINESE_ENTRY.match(text):
            score += 2

        # 2. 文本内多行匹配参考文献模式（块内密度）
        if not score and text_len > 100:
            lines = text.split("\n")
            if len(lines) >= 3:
                ref_line_count = sum(
                    1 for ln in lines
                    if cls._REF_ENTRY_START.match(ln.strip())
                    or cls._REF_CHINESE_ENTRY.match(ln.strip())
                    or cls._REF_HEADING.match(ln.strip())
                )
                if ref_line_count >= len(lines) * 0.5:
                    score += 2

        # 3. 小字号信号（论文字号通常比正文小 1-2pt）
        if font and body_font_size and font.size < body_font_size - 0.5:
            score += 1

        # 4. 文档后半部分（参考文献通常在文末）
        if total_pages > 3 and page_num > total_pages * 0.6:
            score += 1

        # 5. 内容中含 DOI / URL / 期刊卷期号特征
        if re.search(r"DOI[：:\s]|doi\.org/|10\.\d{4,}/|Vol\.\s*\d+|pp\.\s*\d+|"
                     r"[Jj]ournal\s+of|[Jj]\.[\s\d]|（[A-Za-z]+）|"
                     r"硕士学位论文|博士学位论文|arXiv|PMID",
                     text):
            score += 1

        return score


# ── 列表结构分析 ──────────────────────────────────────────

# 列表前缀模式
_ORDERED_LIST_RE = re.compile(
    r"^[\s]*([\d]+|[a-zA-Z]|[ivxlcdm]+|[一二三四五六七八九十]+)[\.\、\)）]\s+"
)
_UNORDERED_LIST_RE = re.compile(
    r"^[\s]*[-•·▪▸►➤✓✅❖■◆●○►*]\s+"
)

# 默认段落缩进宽度（pt）
_DEFAULT_INDENT_WIDTH = 24.0


def enrich_list_structure(
    blocks: list[StructuredBlock],
) -> list[StructuredBlock]:
    """为连续的 LIST_ITEM 块补充嵌套层级和列表类型信息。

    - 通过缩进检测嵌套层级（每级缩进 ~24pt）
    - 通过前缀区分有序/无序列表
    - 原地修改并返回 blocks
    """
    if not blocks:
        return blocks

    i = 0
    while i < len(blocks):
        block = blocks[i]
        if block.layout_tag != LayoutTag.LIST_ITEM.value:
            i += 1
            continue

        # 收集连续的列表项
        list_group: list[tuple[int, object]] = []
        j = i
        while j < len(blocks) and blocks[j].layout_tag == LayoutTag.LIST_ITEM.value:
            list_group.append((j, blocks[j]))
            j += 1

        if not list_group:
            i += 1
            continue

        # 计算基线缩进（第一个列表项或最小缩进）
        x0_values = [
            b.bbox[0] if b.bbox else 0.0  # type: ignore[attr-defined]
            for _, b in list_group
        ]
        base_x0 = min(x0_values) if x0_values else 0.0

        for _idx, b in list_group:
            bbox_x0 = b.bbox[0] if b.bbox else base_x0  # type: ignore[attr-defined]
            # 缩进层级 = (当前缩进 - 基线) / 24pt，向上取整
            indent = max(0.0, bbox_x0 - base_x0)
            level = round(indent / _DEFAULT_INDENT_WIDTH)
            level = max(0, min(level, 4))  # 最多 4 级嵌套

            stripped = b.content.strip()  # type: ignore[attr-defined]
            b.list_type = "ordered" if _ORDERED_LIST_RE.match(stripped) else "unordered"  # type: ignore[attr-defined]
            b.list_level = level  # type: ignore[attr-defined]

        i = j  # 跳过已处理的组

    return blocks
# ── 字号分析 ──────────────────────────────────────────────


class FontAnalyzer:
    """从 PyMuPDF 文本块中提取字体层级画像。"""

    @classmethod
    def profile_page(cls, page_num: int, text_blocks: list[dict[str, Any]]) -> PageFontProfile:
        """从一页的 PyMuPDF text block dicts 构建字体画像。"""
        fonts: list[FontInfo] = []
        sizes: list[float] = []

        for block in text_blocks:
            if block.get("type") != 0:  # type 0 = text
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    size = float(span.get("size", 10))
                    fonts.append(FontInfo(
                        size=size,
                        bold=bool(span.get("flags", 0) & 2**3),  # PDF font flag bit 3 = bold
                        italic=bool(span.get("flags", 0) & 2**1),
                        font_name=span.get("font", ""),
                    ))
                    sizes.append(size)

        if not sizes:
            return PageFontProfile(page_num=page_num)

        # 正文字号 = 出现频率最高的字号
        from collections import Counter
        size_counts = Counter(round(s, 1) for s in sizes)
        body_size = size_counts.most_common(1)[0][0] if size_counts else 10.0
        max_size = max(sizes)

        return PageFontProfile(
            page_num=page_num,
            fonts=fonts,
            body_size=body_size,
            title_size=max(s for s in sizes if s > body_size + 1) if any(s > body_size + 1 for s in sizes) else body_size,
            max_size=max_size,
        )


# ── 阅读顺序恢复 ──────────────────────────────────────────


class ReadingOrder:
    """多栏布局感知的阅读顺序恢复。

    算法：
    1. 将所有块按 y 坐标分组为"行带"
    2. 在每个行带内按 x 坐标从左到右排列
    3. 检测列间隙（x 方向的大空白）来识别分栏

    支持：单栏、双栏、混合布局。
    """

    # 列间隙最小宽度（相对于页面宽度的比例）
    COLUMN_GAP_MIN_RATIO = 0.05

    @classmethod
    def reorder(
        cls,
        blocks: list[dict[str, Any]],
        page_width: float,
        page_height: float,  # noqa: ARG003
    ) -> list[dict[str, Any]]:
        """按人类阅读顺序重新排列块。"""
        if len(blocks) <= 1:
            return blocks

        # 检测列数
        columns = cls._detect_columns(blocks, page_width)

        if len(columns) <= 1:
            # 单栏：简单从上到下
            return sorted(blocks, key=lambda b: (b.get("bbox", (0, 0, 0, 0))[1], b.get("bbox", (0, 0, 0, 0))[0]))

        # 多栏：先分栏，再栏内从上到下，栏间从左到右
        return cls._reorder_columns(blocks, columns, page_width)

    @classmethod
    def _detect_columns(
        cls, blocks: list[dict[str, Any]], page_width: float
    ) -> list[tuple[float, float]]:
        """检测列区域，返回 [(left, right), ...] 列表。"""
        if not blocks:
            return [(0, page_width)]

        # 收集所有块的 x 范围
        x_ranges = []
        for b in blocks:
            bbox = b.get("bbox", (0, 0, 0, 0))
            x_ranges.append((bbox[0], bbox[2]))

        if not x_ranges:
            return [(0, page_width)]

        # 按左边界排序
        x_ranges.sort()

        # 聚类：间隙 > COLUMN_GAP_MIN_RATIO * page_width 视为列分隔
        min_gap = page_width * cls.COLUMN_GAP_MIN_RATIO
        columns: list[list[tuple[float, float]]] = [[x_ranges[0]]]

        for x_range in x_ranges[1:]:
            prev_right = max(r[1] for r in columns[-1])
            if x_range[0] - prev_right > min_gap:
                columns.append([x_range])
            else:
                columns[-1].append(x_range)

        return [(min(r[0] for r in col), max(r[1] for r in col)) for col in columns]

    @classmethod
    def _reorder_columns(
        cls,
        blocks: list[dict[str, Any]],
        columns: list[tuple[float, float]],
        page_width: float,  # noqa: ARG003
    ) -> list[dict[str, Any]]:
        """按栏重新排列块。"""
        result: list[dict[str, Any]] = []

        for col_left, col_right in columns:
            col_blocks = [
                b for b in blocks
                if (b.get("bbox", (0, 0, 0, 0))[0] + b.get("bbox", (0, 0, 0, 0))[2]) / 2 >= col_left
                and (b.get("bbox", (0, 0, 0, 0))[0] + b.get("bbox", (0, 0, 0, 0))[2]) / 2 <= col_right
            ]
            col_blocks.sort(key=lambda b: b.get("bbox", (0, 0, 0, 0))[1])
            result.extend(col_blocks)

        return result


# ── DOCX 样式映射 ──────────────────────────────────────────


class DocxStyleTagger:
    """Word 文档的样式 → LayoutTag 映射。

    DOCX 自带样式层级（Heading 1/2/3, Normal 等），
    比 PDF 更容易恢复语义结构。
    """

    _STYLE_MAP: dict[str, LayoutTag] = {
        "title": LayoutTag.TITLE,
        "heading 1": LayoutTag.HEADING,
        "heading 2": LayoutTag.HEADING,
        "heading 3": LayoutTag.SUBTITLE,
        "heading 4": LayoutTag.SUBTITLE,
        "heading 5": LayoutTag.SUBTITLE,
        "heading 6": LayoutTag.SUBTITLE,
        "subtitle": LayoutTag.SUBTITLE,
        "abstract": LayoutTag.ABSTRACT,
        "normal": LayoutTag.BODY,
        "body text": LayoutTag.BODY,
        "list paragraph": LayoutTag.LIST_ITEM,
        "caption": LayoutTag.CAPTION,
        "footnote text": LayoutTag.FOOTNOTE,
        "footer": LayoutTag.FOOTER,
        "header": LayoutTag.HEADER,
    }

    @classmethod
    def tag(cls, style_name: str) -> LayoutTag:
        """将 DOCX 段落样式映射为 LayoutTag。"""
        normalized = style_name.strip().lower()
        # 去掉多余空格和不可见字符
        normalized = re.sub(r"\s+", " ", normalized)
        return cls._STYLE_MAP.get(normalized, LayoutTag.BODY)


# ── 全局文档级布局分析 ───────────────────────────────────


@dataclass
class LayoutAnalysis:
    """整个文档的版面分析结果。"""

    page_count: int
    page_profiles: list[PageFontProfile] = field(default_factory=list)
    global_body_size: float = 10.0    # 全文档正文字号
    global_title_size: float = 14.0   # 全文档标题字号
    has_multi_column: bool = False
    column_count: int = 1
    header_patterns: set[str] = field(default_factory=set)   # 重复出现的页眉文本
    footer_patterns: set[str] = field(default_factory=set)   # 重复出现的页脚文本


def analyze_document_layout(
    page_count: int,
    page_text_blocks: dict[int, list[dict[str, Any]]],
    page_dimensions: dict[str, dict[str, float]],
) -> LayoutAnalysis:
    """对整份文档进行版面分析。

    Args:
        page_count: 总页数
        page_text_blocks: {页码: [PyMuPDF text block dict, ...]}
        page_dimensions: {页码: {"width": w, "height": h}}
    """
    profiles: list[PageFontProfile] = []

    for page_num in range(1, page_count + 1):
        blocks = page_text_blocks.get(page_num, [])
        profile = FontAnalyzer.profile_page(page_num, blocks)
        profiles.append(profile)

    # 全局正文字号 = 各页正文字号的众数
    if profiles:
        from collections import Counter
        body_sizes = Counter(round(p.body_size, 1) for p in profiles)
        global_body_size = body_sizes.most_common(1)[0][0] if body_sizes else 10.0
        global_title_size = max(p.max_size for p in profiles) if profiles else 14.0
    else:
        global_body_size = 10.0
        global_title_size = 14.0

    # 搜集重复页眉/页脚文本（跨页出现 ≥3 次的前几行文字）
    first_lines: list[str] = []
    last_lines: list[str] = []
    for page_num in range(1, page_count + 1):
        blocks = page_text_blocks.get(page_num, [])
        if not blocks:
            continue
        page_dim = page_dimensions.get(str(page_num), {})
        ph = page_dim.get("height", 842)
        top_blocks = [
            b for b in blocks
            if b.get("bbox", (0, 0, 0, 0))[1] < ph * Region.HEADER_RATIO
        ]
        bottom_blocks = [
            b for b in blocks
            if b.get("bbox", (0, 0, 0, 0))[1] > ph * (1 - Region.FOOTER_RATIO)
        ]
        for tb in top_blocks:
            text = _extract_block_text(tb).strip()
            if text and len(text) < 200:
                first_lines.append(text)
        for bb in bottom_blocks:
            text = _extract_block_text(bb).strip()
            if text and len(text) < 100:
                last_lines.append(text)

    from collections import Counter
    header_patterns = {t for t, c in Counter(first_lines).items() if c >= 3}
    footer_patterns = {t for t, c in Counter(last_lines).items() if c >= 3}

    if header_patterns:
        logger.info(f"检测到页眉模式 ({len(header_patterns)} 种): {list(header_patterns)[:3]}...")
    if footer_patterns:
        logger.info(f"检测到页脚模式 ({len(footer_patterns)} 种): {list(footer_patterns)[:3]}...")

    return LayoutAnalysis(
        page_count=page_count,
        page_profiles=profiles,
        global_body_size=global_body_size,
        global_title_size=global_title_size,
        header_patterns=header_patterns,
        footer_patterns=footer_patterns,
    )


def _extract_block_text(block: dict[str, Any]) -> str:
    """从 PyMuPDF block dict 中提取纯文本。"""
    parts: list[str] = []
    for line in block.get("lines", []):
        for span in line.get("spans", []):
            text = span.get("text", "")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts)
