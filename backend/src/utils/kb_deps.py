"""知识库文档解析依赖检查。"""

from __future__ import annotations

# (import 名, 友好名称)
_KB_DOC_DEPS: tuple[tuple[str, str], ...] = (
    ("pdfplumber", "pdfplumber"),
    ("fitz", "pymupdf"),
    ("docx", "python-docx"),
)


def missing_kb_document_deps() -> list[str]:
    """返回未安装的依赖友好名称列表。"""
    missing: list[str] = []
    for module_name, label in _KB_DOC_DEPS:
        try:
            __import__(module_name)
        except ImportError:
            missing.append(label)
    return missing
