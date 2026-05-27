"""
分块数据模型 —— 文档解析 → 分块 → 嵌入 管线中的核心数据结构。

包含两个核心数据类：
- StructuredBlock：解析后的版面最小单元（来自 MinerU/pdfplumber 等解析器）
- ChunkResult：分块后的 metadata-aware chunk（供 embedding 和检索引擎使用）
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class StructuredBlock:
    """文档中的结构化内容块——解析后的最小单元。

    由文档解析器（MinerU、pdfplumber 等）产出，包含版面位置、
    语义标签、章节归属等结构化信息。
    """

    block_type: str  # text | table | image | code | formula
    content: str
    page_number: int
    bbox: tuple[float, float, float, float] | None = None
    table_html: str | None = None
    table_data: list[list[str]] | None = None
    image_path: str | None = None
    section_title: str | None = None
    section_path: str | None = None  # 章节层级路径
    # 图片描述（非 OCR，语义理解）
    image_description: str | None = None
    image_caption: str | None = None
    ocr_status: str | None = None  # success | empty | failed | disabled
    ocr_error: str | None = None
    # 表格标题/说明
    table_caption: str | None = None
    # 版面语义标签（LayoutTag 值）
    layout_tag: str | None = None
    # 图片原始宽高（用于前端等比例显示）
    image_width: int | None = None
    image_height: int | None = None
    # 交叉引用：同页关联的图片/表格/脚注引用
    image_refs: list[str] | None = None
    table_refs: list[str] | None = None
    # 列表结构
    list_level: int = 0
    list_type: str = ""


@dataclass
class ChunkResult:
    """分块结果——metadata-aware 结构化 chunk。

    每个 chunk 自包含完整的语义上下文：
    title / section_path / doc_category / layout_tag / table_refs / image_refs
    embedding 时不是嵌入纯文本，而是嵌入这些结构化字段的组合。
    """

    chunk_id: str
    content: str
    chunk_index: int
    page_start: int
    page_end: int
    chunk_type: str  # text | table | image | code | formula | reference
    parent_chunk_id: str | None = None
    bbox: tuple[float, float, float, float] | None = None
    table_html: str | None = None
    table_data: list[list[str]] | None = None
    image_path: str | None = None
    section_title: str | None = None
    section_path: str | None = None
    ocr_status: str | None = None
    ocr_error: str | None = None
    image_caption: str | None = None
    image_description: str | None = None
    table_caption: str | None = None
    # Agentic RAG 增强
    content_summary: str | None = None  # 分块内容摘要（用于检索增强）
    is_heading: bool = False
    heading_level: int = 0
    doc_category: str | None = None
    # 版面语义标签
    layout_tag: str | None = None
    # 列表结构
    list_level: int = 0
    list_type: str = ""

    # 文档结构感知字段（metadata-aware retrieval 核心）
    title: str | None = None  # chunk 归属的章节标题（如 "3.2 数字孪生系统"）
    table_refs: list[str] | None = None  # 同页关联表格的 chunk_id 列表
    image_refs: list[str] | None = None  # 同页关联图片的 chunk_id 列表

    # 图片原始宽高
    image_width: int | None = None
    image_height: int | None = None
