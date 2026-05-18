"""
MinerU PDF 解析器 —— 基于深度学习的版面分析。

MinerU (magic-pdf) 使用 DocLayoutYOLO 做版面检测，能准确识别：
  - 标题 / 章节标题 / 副标题
  - 正文段落
  - 表格（输出 Markdown 格式）
  - 图片 + 图注
  - 公式（LaTeX 格式）
  - 页眉 / 页脚
  - 参考文献
  - 列表

这是工业级的 PDF→结构化输出管线，准确度远高于启发式方法。

用法：
    parser = MinerUParser()
    if parser.available:
        blocks, page_count, metadata = parser.parse(file_path)
    else:
        # 回退到默认管线

输出格式与 pdfplumber 管线完全兼容（StructuredBlock[]）。
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.config import get_settings
from src.services.chunking_service import StructuredBlock
from src.services.document_processors.layout import LayoutTag

# ── Layout label → our tag mapping ──────────────────────────

# MinerU 输出的 layoutno / category_type → LayoutTag
_MINERU_TAG_MAP: dict[str, str] = {
    # 标题层级
    "title": LayoutTag.TITLE.value,
    "section_header": LayoutTag.HEADING.value,
    "subtitle": LayoutTag.SUBTITLE.value,
    "para_title": LayoutTag.HEADING.value,
    # 正文
    "text": LayoutTag.BODY.value,
    "para_text": LayoutTag.BODY.value,
    "paragraph": LayoutTag.BODY.value,
    # 摘要/关键词
    "abstract": LayoutTag.ABSTRACT.value,
    "keywords": LayoutTag.KEYWORDS.value,
    # 特殊内容
    "table": LayoutTag.TABLE_BODY.value,
    "table_caption": LayoutTag.CAPTION.value,
    "image": LayoutTag.IMAGE_REGION.value,
    "image_caption": LayoutTag.CAPTION.value,
    "picture": LayoutTag.IMAGE_REGION.value,
    "figure": LayoutTag.IMAGE_REGION.value,
    "figure_caption": LayoutTag.CAPTION.value,
    "formula": LayoutTag.CODE.value,
    "equation": LayoutTag.CODE.value,
    # 页眉/页脚
    "header": LayoutTag.HEADER.value,
    "footer": LayoutTag.FOOTER.value,
    "page_number": LayoutTag.FOOTER.value,
    # 其他
    "footnote": LayoutTag.FOOTNOTE.value,
    "reference": LayoutTag.REFERENCE.value,
    "ref_text": LayoutTag.REFERENCE.value,
    "list": LayoutTag.LIST_ITEM.value,
    "list_item": LayoutTag.LIST_ITEM.value,
    "code": LayoutTag.CODE.value,
    "seal": LayoutTag.BODY.value,   # 印章 → 按正文处理
    "abandon": LayoutTag.BODY.value,  # 噪声区 → 正文
}


class MinerUParser:
    """MinerU PDF 解析器封装。

    自动检测 magic_pdf 是否安装；未安装时 available=False 并回退。
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._checked = False
        self._available = False

    @property
    def available(self) -> bool:
        """MinerU 是否可用。"""
        if not self._checked:
            self._available = self._detect()
            self._checked = True
        return self._available

    def _detect(self) -> bool:
        """检测 magic_pdf 是否已安装。"""
        if self._settings.kb_pdf_parser != "mineru":
            return False
        try:
            import magic_pdf  # noqa: F401
            logger.info("MinerU (magic-pdf) 检测成功，启用深度学习版面分析")
            return True
        except ImportError:
            logger.warning(
                "MinerU 未安装（pip install magic-pdf），回退到默认 PDF 解析器。"
                "安装方法: uv sync --group mineru 或 pip install magic-pdf"
            )
            return False

    def parse(
        self,
        file_path: str,
        *,
        output_dir: str | None = None,
    ) -> tuple[list[StructuredBlock], int, dict] | None:
        """用 MinerU 解析 PDF，返回 (blocks, page_count, metadata)。

        失败时返回 None，调用方应回退到默认管线。
        """
        if not self.available:
            return None

        try:
            return self._do_parse(file_path, output_dir)
        except Exception as e:
            logger.error(f"MinerU 解析失败，回退到默认管线: {e}")
            return None

    def _do_parse(
        self, file_path: str, output_dir: str | None
    ) -> tuple[list[StructuredBlock], int, dict]:
        """调用 magic-pdf 引擎解析。"""
        import fitz  # PyMuPDF

        # 设置模型目录（避免每次重新下载）
        settings = get_settings()
        if settings.mineru_models_dir:
            os.environ.setdefault("MINERU_MODELS_DIR", settings.mineru_models_dir)

        # 读取 PDF
        pdf_bytes = Path(file_path).read_bytes()

        # 用 PyMuPDF 获取页数
        doc = fitz.open(file_path)
        page_count = doc.page_count
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
        }
        doc.close()

        # 临时输出目录
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="mineru_")

        # ── 调用 MinerU 引擎 ──
        import magic_pdf.model as model_config
        model_config.__use_inside_model__ = True

        from magic_pdf.pipe.UNIPipe import UNIPipe
        from magic_pdf.rw.DiskReaderWriter import DiskReaderWriter

        image_writer = DiskReaderWriter(output_dir)

        jso_useful_key: dict[str, Any] = {
            "_pdf_type": "",
            "model_list": [],
        }

        pipe = UNIPipe(pdf_bytes, jso_useful_key, image_writer)
        pipe.pipe_classify()
        pipe.pipe_parse()

        # 获取统一格式输出
        content_list = pipe.pipe_mk_uni_format(output_dir, drop_mode="none")

        # 转换为我们 StructuredBlock 格式
        blocks = self._convert_blocks(content_list, page_count)

        logger.info(
            f"MinerU 解析完成: pages={page_count}, blocks={len(blocks)}, "
            f"tables={sum(1 for b in blocks if b.block_type=='table')}, "
            f"images={sum(1 for b in blocks if b.block_type=='image')}"
        )
        return blocks, page_count, metadata

    def _convert_blocks(
        self, content_list: list[dict[str, Any]], page_count: int
    ) -> list[StructuredBlock]:
        """将 MinerU 的 content_list 转换为 StructuredBlock 列表。

        同时完成：
        - 阅读顺序恢复（MinerU 输出已按阅读顺序排列）
        - 语义标签映射（layoutno → LayoutTag）
        - 表格 HTML/Markdown 生成
        """
        blocks: list[StructuredBlock] = []

        for item in content_list:
            block_type = item.get("type", "text")
            mineru_layout = item.get("layoutno", "")
            text = item.get("text", "") or ""
            bbox_list = item.get("bbox", [])
            page_idx = item.get("page_idx", 0)
            page_num = page_idx + 1  # MinerU 使用 0-indexed page_idx

            if page_num > page_count:
                page_num = page_count

            bbox = None
            if len(bbox_list) == 4:
                bbox = tuple(bbox_list)

            layout_tag = _MINERU_TAG_MAP.get(mineru_layout, LayoutTag.BODY.value)

            if block_type == "table":
                # MinerU 输出表格为 Markdown / HTML / 纯文本
                table_html = item.get("table_html", "") or self._text_to_html_table(text)
                table_data = item.get("table_body", []) or self._markdown_table_to_data(text)
                if not table_data:
                    # Last resort: wrap as text
                    blocks.append(StructuredBlock(
                        block_type="text",
                        content=text,
                        page_number=page_num,
                        bbox=bbox,
                        layout_tag=layout_tag,
                    ))
                    continue
                blocks.append(StructuredBlock(
                    block_type="table",
                    content=text if text else self._table_data_to_md(table_data),
                    page_number=page_num,
                    bbox=bbox,
                    table_html=table_html,
                    table_data=table_data,
                    layout_tag=layout_tag,
                ))

            elif block_type == "image":
                img_path = item.get("image_path", "")
                image_caption = item.get("image_caption", "")  # MinerU may provide caption separately
                blocks.append(StructuredBlock(
                    block_type="image",
                    content=f"[图片] {image_caption or f'第{page_num}页图片'}",
                    page_number=page_num,
                    bbox=bbox,
                    image_path=img_path if img_path else None,
                    image_caption=image_caption if image_caption else None,
                    layout_tag=layout_tag,
                ))

            else:
                # text, title, header, footer, formula, etc.
                if not text.strip():
                    continue
                # 公式 → code block
                if mineru_layout in ("formula", "equation"):
                    blocks.append(StructuredBlock(
                        block_type="code",
                        content=text,
                        page_number=page_num,
                        bbox=bbox,
                        layout_tag=layout_tag,
                    ))
                else:
                    blocks.append(StructuredBlock(
                        block_type="text",
                        content=text,
                        page_number=page_num,
                        bbox=bbox,
                        layout_tag=layout_tag,
                    ))

        return blocks

    # ── 辅助转换 ──────────────────────────────────────────

    @staticmethod
    def _markdown_table_to_data(md_text: str) -> list[list[str]]:
        """从 Markdown 表格文本解析为二维列表。"""
        lines = [ln.strip() for ln in md_text.split("\n") if ln.strip().startswith("|")]
        if len(lines) < 2:
            return []
        data: list[list[str]] = []
        for ln in lines:
            cells = [c.strip() for c in ln.split("|")]
            # 移除首尾空元素
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
            # 跳过分隔线
            if all(re.fullmatch(r"[-: ]+", c) for c in cells):
                continue
            data.append(cells)
        return data

    @staticmethod
    def _table_data_to_md(data: list[list[str]]) -> str:
        """二维列表 → Markdown 表格。"""
        if not data:
            return ""
        rows = []
        for i, row in enumerate(data):
            cleaned = [str(c).replace("\n", " ").replace("|", "\\|").strip() for c in row]
            rows.append("| " + " | ".join(cleaned) + " |")
            if i == 0:
                rows.append("| " + " | ".join(["---"] * len(cleaned)) + " |")
        return "\n".join(rows)

    @staticmethod
    def _text_to_html_table(text: str) -> str:
        """纯文本表格 → HTML（回退方案）。"""
        if not text.strip():
            return ""
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        parts = ['<div class="kb-table-wrapper"><table class="kb-table">']
        for i, line in enumerate(lines):
            tag = "th" if i == 0 else "td"
            cells = line.split("\t") if "\t" in line else [line]
            cells_html = "".join(f"<{tag}>{c.strip()}</{tag}>" for c in cells if c.strip())
            parts.append(f"<tr>{cells_html}</tr>")
        parts.append("</table></div>")
        return "\n".join(parts)


# ── 过滤页眉页脚 ──────────────────────────────────────────


def filter_noise_blocks(blocks: list[StructuredBlock]) -> list[StructuredBlock]:
    """过滤掉应跳过 embedding 的块（页眉、页脚等）。

    注意：此函数用于 embedding/chunking 前过滤，
    原始 blocks 列表仍保留供页面查看器使用。
    """
    noise_tags = {LayoutTag.HEADER.value, LayoutTag.FOOTER.value}
    filtered = [b for b in blocks if b.layout_tag not in noise_tags]
    removed = len(blocks) - len(filtered)
    if removed:
        logger.info(f"过滤噪声块: 移除 {removed} 个（页眉/页脚）")
    return filtered


def is_noise_block(block: StructuredBlock) -> bool:
    """判断是否为噪声块（不应参与 embedding）。"""
    return block.layout_tag in {LayoutTag.HEADER.value, LayoutTag.FOOTER.value}
