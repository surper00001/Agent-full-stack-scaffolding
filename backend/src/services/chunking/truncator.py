"""
Content Truncator — 内容截断工具。

从 ChunkingService 提取的独立工具模块，负责：
- 内容硬截断（保护 embedding 模型）
- 智能边界截断（句末/段末）
- 字符计数（中英文混合）
"""

import re
from typing import ClassVar

# 内容上限常量
HARD_CONTENT_MAX_CHARS = 5000
SPECIAL_CONTENT_MAX_CHARS = 2000


def hard_cap_content(content: str, max_chars: int | None = None) -> str:
    """强制截断过长内容，在句末/段末智能截断。"""
    limit = max_chars or HARD_CONTENT_MAX_CHARS
    if len(content) <= limit:
        return content
    truncated = content[:limit]
    for sep in ("\n\n", "。", ". ", "\n", " ", ""):
        idx = truncated.rfind(sep)
        if idx > limit // 2:
            return truncated[:idx + len(sep)] + f"\n...(已截断，原{len(content)}字符)"
    return truncated + f"...(已截断，原{len(content)}字符)"


def truncate_content_for_embed(content: str, max_chars: int | None = None) -> str:
    """截断过长内容，保证嵌入时不超出模型上限。"""
    limit = max_chars or SPECIAL_CONTENT_MAX_CHARS
    if len(content) <= limit:
        return content
    truncated = content[:limit]
    for sep in ("\n\n", "。", ". ", "\n", " "):
        idx = truncated.rfind(sep)
        if idx > limit // 2:
            return truncated[: idx + len(sep)] + f"\n... (内容已截断，共 {len(content)} 字符)"
    return truncated + f"... (内容已截断，共 {len(content)} 字符)"


def char_count(text: str) -> int:
    """中英文混合字符计数（按视觉宽度）。"""
    count = 0
    for c in text:
        if ord(c) < 128:
            count += 1  # ASCII
        elif "一" <= c <= "鿿" or "　" <= c <= "〿":
            count += 2  # 中文/日文
        else:
            count += 1
    return count


def advance_by_char_count(text: str, start: int, max_count: int) -> int:
    """从 start 位置前进 max_count 个字符宽度。"""
    pos = start
    consumed = 0
    while pos < len(text) and consumed < max_count:
        c = text[pos]
        consumed += 2 if ("一" <= c <= "鿿" or "　" <= c <= "〿") else 1
        pos += 1
    return pos


def tail_by_char_count(text: str, max_count: int) -> str:
    """从文本末尾截取不超过 max_count 字符宽度的内容。"""
    total = char_count(text)
    if total <= max_count:
        return text
    pos = 0
    accumulated = 0
    skip = total - max_count
    while pos < len(text) and accumulated < skip:
        c = text[pos]
        accumulated += 2 if ("一" <= c <= "鿿" or "　" <= c <= "〿") else 1
        pos += 1
    return text[pos:]


def detect_code_language(text: str) -> str:
    """检测代码片段语言。"""
    if re.search(r"(?:df\.|plt\.|pd\.|np\.|sns\.)", text):
        return "python"
    if re.search(r"(?:fmt\.|func\s|package\s)", text):
        return "go"
    if re.search(r"(?:console\.|const\s|let\s|var\s|=>)", text):
        return "javascript"
    if re.search(r"(?:System\.|public\s(?:class|void|static)|import\sjava)", text):
        return "java"
    if re.search(r"(?:using\sSystem|namespace\s)", text):
        return "csharp"
    if re.search(r"<\w+>|<\/\w+>", text):
        return "html"
    if re.search(r"(?:SELECT\s|INSERT\s|CREATE\sTABLE)", text, re.IGNORECASE):
        return "sql"
    if re.search(r"^\s*(?:###|~~~|```)", text, re.MULTILINE):
        return "markdown"
    if re.search(r"#include|int\s+main", text):
        return "cpp"
    return ""
