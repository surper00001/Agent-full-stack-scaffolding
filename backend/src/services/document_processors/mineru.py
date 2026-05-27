"""
MinerU PDF 解析器 —— 基于深度学习的版面分析。

MinerU v3 使用 DocLayoutYOLO + VLM hybrid 做版面检测，能准确识别：
  - 标题 / 章节标题 / 副标题
  - 正文段落
  - 表格（输出 HTML 格式）
  - 图片 + 图注
  - 公式（LaTeX 格式）
  - 页眉 / 页脚
  - 参考文献
  - 列表
  - 代码块

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

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from loguru import logger

from src.core.config import get_settings
from src.services.chunking_service import StructuredBlock
from src.services.document_processors.layout import LayoutTag

# ── MinerU v3 content_list type → LayoutTag ──────────────────
# v3 的 type 字段直接对应 BlockType / ContentType
_MINERU_V3_TAG_MAP: dict[str, str] = {
    # 标题层级
    "title": LayoutTag.HEADING.value,
    "doc_title": LayoutTag.TITLE.value,
    "paragraph_title": LayoutTag.HEADING.value,
    # 正文
    "text": LayoutTag.BODY.value,
    "paragraph": LayoutTag.BODY.value,
    # 摘要
    "abstract": LayoutTag.ABSTRACT.value,
    # 表格
    "table": LayoutTag.TABLE_BODY.value,
    "table_body": LayoutTag.TABLE_BODY.value,
    "table_caption": LayoutTag.CAPTION.value,
    # 图片
    "image": LayoutTag.IMAGE_REGION.value,
    "image_body": LayoutTag.IMAGE_REGION.value,
    "image_caption": LayoutTag.CAPTION.value,
    "chart": LayoutTag.IMAGE_REGION.value,
    # 公式
    "equation": LayoutTag.CODE.value,
    "interline_equation": LayoutTag.CODE.value,
    # 页眉/页脚（将被 filter_noise_blocks 过滤）
    "header": LayoutTag.HEADER.value,
    "footer": LayoutTag.FOOTER.value,
    "page_header": LayoutTag.HEADER.value,
    "page_footer": LayoutTag.FOOTER.value,
    "page_number": LayoutTag.FOOTER.value,
    "aside_text": LayoutTag.FOOTER.value,
    # 脚注/参考文献
    "footnote": LayoutTag.FOOTNOTE.value,
    "page_footnote": LayoutTag.FOOTNOTE.value,
    "ref_text": LayoutTag.REFERENCE.value,
    "reference": LayoutTag.REFERENCE.value,
    # 列表
    "list": LayoutTag.LIST_ITEM.value,
    "index": LayoutTag.LIST_ITEM.value,
    # 代码
    "code": LayoutTag.CODE.value,
    "algorithm": LayoutTag.CODE.value,
    # 其他
    "seal": LayoutTag.BODY.value,
}


class MinerUParser:
    """MinerU v3 PDF 解析器封装。

    通过 subprocess 调用 mineru CLI（v3 API），解析其 content_list JSON 输出。
    自动检测 mineru 是否安装；未安装时 available=False 并回退。
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
        """检测 mineru CLI 是否可用。"""
        if self._settings.kb_pdf_parser not in ("mineru", "auto"):
            return False

        mineru_bin = shutil.which("mineru")
        if not mineru_bin:
            logger.warning(
                "MinerU CLI 未找到，回退到默认 PDF 解析器。"
                "安装方法: uv add 'mineru[core]' 并在 .env 设置 KB_PDF_PARSER=mineru"
            )
            return False

        logger.info(f"MinerU CLI 检测成功: {mineru_bin}")

        # 检查模型是否已下载
        models_ready = self._check_models()
        if not models_ready:
            logger.warning(
                "MinerU 模型未下载，回退到默认 PDF 解析器。"
                "下载模型: uv run mineru-models-download -s huggingface -m pipeline"
            )
            return False

        return True

    @staticmethod
    def _check_models() -> bool:
        """检查 MinerU 模型缓存目录是否存在（modelscope 或 huggingface）。"""
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, ".cache", "modelscope", "hub"),
            os.path.join(home, ".cache", "huggingface", "hub"),
            os.path.join(home, ".cache", "mineru", "models"),
            os.path.join(home, ".mineru", "models"),
        ]
        # 也检查 MINERU_MODELS_DIR 环境变量
        env_dir = os.environ.get("MINERU_MODELS_DIR", "")
        if env_dir:
            candidates.insert(0, env_dir)

        for c in candidates:
            if os.path.isdir(c) and any(
                os.path.isdir(os.path.join(c, d))
                for d in os.listdir(c)
                if not d.startswith(".") and os.path.isdir(os.path.join(c, d))
            ):
                logger.info(f"MinerU 模型缓存目录: {c}")
                return True
        return False

    def parse(
        self,
        file_path: str,
        *,
        output_dir: str | None = None,
    ) -> tuple[list[StructuredBlock], int, dict] | None:
        """用 MinerU v3 解析 PDF，返回 (blocks, page_count, metadata)。

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
        """调用 mineru v3 CLI 解析 PDF，读取 content_list JSON 输出。"""
        import fitz  # PyMuPDF

        # 设置模型目录
        settings = get_settings()
        env = os.environ.copy()
        # 限制 MinerU 子进程的 CPU 线程，避免与主进程争抢全部核心
        env.setdefault("OMP_NUM_THREADS", "4")
        env.setdefault("MKL_NUM_THREADS", "4")
        env.setdefault("OPENBLAS_NUM_THREADS", "4")
        if settings.mineru_models_dir:
            env["MINERU_MODELS_DIR"] = settings.mineru_models_dir
        if settings.mineru_device:
            env["MINERU_DEVICE"] = settings.mineru_device
        if settings.mineru_model_source:
            env["MINERU_MODEL_SOURCE"] = settings.mineru_model_source

        # 用 PyMuPDF 获取页数和元数据
        doc = fitz.open(file_path)
        page_count = doc.page_count
        metadata = {
            "title": doc.metadata.get("title", ""),
            "author": doc.metadata.get("author", ""),
        }
        doc.close()

        # MinerU 输出目录 —— 放在项目 data 目录下，避免系统盘堆积
        pdf_name = Path(file_path).stem
        if output_dir is None:
            output_dir = str(Path(settings.kb_storage_dir).resolve().parent / "mineru_output")
        os.makedirs(output_dir, exist_ok=True)
        # 在命名目录下创建唯一子目录，防止并发冲突
        output_dir = tempfile.mkdtemp(prefix=f"{pdf_name}_", dir=output_dir)

        # ── 调用 MinerU v3 CLI ──
        cmd = [
            shutil.which("mineru") or "mineru",
            "-p", file_path,
            "-o", output_dir,
            "-b", settings.mineru_backend,
            "-m", "auto",
            "-l", "ch",
        ]
        logger.info(f"MinerU v3 解析开始: {file_path}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
        if result.returncode != 0:
            # 优先展示 stderr 尾部（含真正的错误原因），而不是开头（只是启动日志）
            stderr_tail = result.stderr.strip().split("\n")[-20:]
            error_detail = "\n".join(stderr_tail) or result.stdout.strip()
            if not error_detail.strip():
                error_detail = f"stdout: {result.stdout[-500:]}\nstderr: {result.stderr[-500:]}"
            raise RuntimeError(
                f"MinerU CLI 失败 (exit={result.returncode}):\n{error_detail}"
            )

        # ── 读取 content_list JSON ──
        # MinerU v3 不同版本输出路径略有差异，按优先级搜索：
        #   1. output_dir/{pdf_name}/{pdf_name}_content_list.json（旧版）
        #   2. output_dir/{pdf_name}/auto/{pdf_name}_content_list.json（新版 v3）
        #   3. output_dir/{pdf_name}_content_list.json（平铺）
        content_list_path = None
        candidates = [
            Path(output_dir) / pdf_name / f"{pdf_name}_content_list.json",
            Path(output_dir) / pdf_name / "auto" / f"{pdf_name}_content_list.json",
            Path(output_dir) / f"{pdf_name}_content_list.json",
        ]
        for candidate in candidates:
            if candidate.exists():
                content_list_path = candidate
                break

        if content_list_path is None:
            # 列出 output_dir 内容帮助排查
            found_files = list(Path(output_dir).rglob("*.json"))
            logger.warning(
                f"未找到 content_list JSON，output_dir 中的 JSON 文件: "
                f"{[str(f) for f in found_files[:10]]}"
            )
            raise RuntimeError("MinerU 解析完成但未生成 content_list JSON 文件")

        with open(content_list_path, encoding="utf-8") as f:
            content_list = json.load(f)

        if not isinstance(content_list, list):
            raise RuntimeError(f"content_list JSON 格式异常: 期望 list，实际 {type(content_list)}")

        # ── 转换为我们 StructuredBlock 格式 ──
        image_dir = str(content_list_path.parent / "images")
        blocks = self._convert_blocks_v3(content_list, page_count, image_dir)

        logger.info(
            f"MinerU v3 解析完成: pages={page_count}, blocks={len(blocks)}, "
            f"tables={sum(1 for b in blocks if b.block_type=='table')}, "
            f"images={sum(1 for b in blocks if b.block_type=='image')}"
        )
        return blocks, page_count, metadata

    def _convert_blocks_v3(
        self,
        content_list: list[dict[str, Any]],
        page_count: int,
        image_dir: str = "",
    ) -> list[StructuredBlock]:
        """将 MinerU v3 content_list JSON 转换为 StructuredBlock 列表。

        v3 输出格式（来自 pipeline_middle_json_mkcontent.make_blocks_to_content_list）:
        {
            "type": "text" | "table" | "image" | "chart" | "equation" | "code" | ...,
            "text": "...",
            "text_level": 1-3 (for titles),
            "bbox": [x0, y0, x1, y1],
            "page_idx": 0,
            "img_path": "images/xxx.png",
            "table_body": "<table>...</table>",
            "table_caption": ["Table 1: ..."],
            "image_caption": ["Figure 1: ..."],
        }
        """
        blocks: list[StructuredBlock] = []

        for item in content_list:
            if not isinstance(item, dict):
                continue

            block_type_raw = item.get("type", "text")
            text = item.get("text", "") or ""
            bbox_list = item.get("bbox", [])
            page_idx = item.get("page_idx", 0)
            page_num = page_idx + 1  # v3 使用 0-indexed page_idx

            if page_num > page_count:
                page_num = page_count

            bbox = None
            if isinstance(bbox_list, list) and len(bbox_list) == 4:
                bbox = tuple(bbox_list)

            # ── 按 v3 类型分发 ──
            if block_type_raw in ("table", "table_body"):
                table_html = item.get("table_body", "") or item.get("html", "")
                # 尝试从 Markdown 文本重建表格数据
                table_data = self._markdown_table_to_data(
                    text if not table_html else ""
                )
                # 表格标题
                captions = item.get("table_caption") or item.get("caption") or []
                table_caption = captions[0] if isinstance(captions, list) and captions else ""

                if not table_html and not table_data:
                    # 无法解析的表格，降级为文本
                    blocks.append(StructuredBlock(
                        block_type="text",
                        content=text or f"[表格] {table_caption}",
                        page_number=page_num,
                        bbox=bbox,
                        table_caption=table_caption,
                        layout_tag=LayoutTag.TABLE_BODY.value,
                    ))
                    continue

                if not table_data and table_html:
                    table_data = []

                blocks.append(StructuredBlock(
                    block_type="table",
                    content=text or self._table_data_to_md(table_data),
                    page_number=page_num,
                    bbox=bbox,
                    table_html=table_html,
                    table_data=table_data if table_data else None,
                    table_caption=table_caption,
                    layout_tag=LayoutTag.TABLE_BODY.value,
                ))

            elif block_type_raw in ("image", "image_body", "chart"):
                img_path = item.get("img_path", "") or item.get("image_path", "")
                captions = item.get("image_caption") or item.get("chart_caption") or []
                image_caption = captions[0] if isinstance(captions, list) and captions else ""

                img_bytes = None
                ext = "png"
                # v3 输出相对路径：images/xxx.png
                if img_path and image_dir:
                    full_img = Path(image_dir) / Path(img_path).name
                    if full_img.exists():
                        img_path = str(full_img)
                    else:
                        abs_img = Path(image_dir).parent / img_path
                        if abs_img.exists():
                            img_path = str(abs_img)
                    if img_path:
                        try:
                            img_bytes = Path(img_path).read_bytes()
                            ext = Path(img_path).suffix.lstrip(".") or "png"
                        except Exception:
                            logger.warning(f"MinerU 图片读取失败: {img_path}")

                if img_bytes is None:
                    logger.warning(f"MinerU 图片缺失，已跳过: page={page_num}, caption={image_caption}")
                    continue

                # 提取图片原始尺寸
                img_width, img_height = None, None
                try:
                    from io import BytesIO

                    from PIL import Image
                    with Image.open(BytesIO(img_bytes)) as pil_img:
                        img_width, img_height = pil_img.size
                except Exception:
                    pass

                blocks.append(StructuredBlock(
                    block_type="image",
                    content=image_caption or f"[图片] 第{page_num}页",
                    page_number=page_num,
                    bbox=bbox,
                    image_path=img_path,
                    image_caption=image_caption,
                    layout_tag=LayoutTag.IMAGE_REGION.value,
                    image_width=img_width,
                    image_height=img_height,
                ))

            elif block_type_raw in ("equation", "interline_equation"):
                text_format = item.get("text_format", "")
                content = text
                if text_format == "latex":
                    content = f"$$\n{text}\n$$"
                blocks.append(StructuredBlock(
                    block_type="code",
                    content=content,
                    page_number=page_num,
                    bbox=bbox,
                    layout_tag=LayoutTag.CODE.value,
                ))

            elif block_type_raw in ("code", "algorithm"):
                blocks.append(StructuredBlock(
                    block_type="code",
                    content=text,
                    page_number=page_num,
                    bbox=bbox,
                    layout_tag=LayoutTag.CODE.value,
                ))

            else:
                # text, title, header, footer, list, abstract, ref_text, seal, ...
                if not text.strip():
                    continue

                layout_tag = _MINERU_V3_TAG_MAP.get(block_type_raw, LayoutTag.BODY.value)

                # 标题级别 → 保留为 section_title 信号
                text_level = item.get("text_level", 0)
                section_title = None
                if text_level and text_level > 0 and block_type_raw in ("text", "title"):
                    section_title = text
                    layout_tag = LayoutTag.HEADING.value if text_level <= 2 else LayoutTag.SUBTITLE.value

                blocks.append(StructuredBlock(
                    block_type="text",
                    content=text,
                    page_number=page_num,
                    bbox=bbox,
                    section_title=section_title,
                    layout_tag=layout_tag,
                ))

        return blocks

    # ── 辅助函数 ──────────────────────────────────────────

    @staticmethod
    def _markdown_table_to_data(md_text: str) -> list[list[str]]:
        """从 Markdown 表格文本解析为二维列表。"""
        lines = [ln.strip() for ln in md_text.split("\n") if ln.strip().startswith("|")]
        if len(lines) < 2:
            return []
        data: list[list[str]] = []
        for ln in lines:
            cells = [c.strip() for c in ln.split("|")]
            if cells and cells[0] == "":
                cells = cells[1:]
            if cells and cells[-1] == "":
                cells = cells[:-1]
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


# ── 保留对外接口兼容 ──────────────────────────────────────


def filter_noise_blocks(blocks: list[StructuredBlock]) -> list[StructuredBlock]:
    """过滤掉应跳过 embedding 的块（页眉、页脚等）。

    注意：此函数用于 embedding/chunking 前过滤，
    原始 blocks 列表仍保留供页面查看器使用。
    """
    noise_tags = {LayoutTag.HEADER.value, LayoutTag.FOOTER.value, LayoutTag.TEMPLATE_NOISE.value}
    filtered = [b for b in blocks if b.layout_tag not in noise_tags]
    removed = len(blocks) - len(filtered)
    if removed:
        logger.info(f"过滤噪声块: 移除 {removed} 个（页眉/页脚）")
    return filtered


def is_noise_block(block: StructuredBlock) -> bool:
    """判断是否为噪声块（不应参与 embedding）。"""
    return block.layout_tag in {LayoutTag.HEADER.value, LayoutTag.FOOTER.value, LayoutTag.TEMPLATE_NOISE.value}
