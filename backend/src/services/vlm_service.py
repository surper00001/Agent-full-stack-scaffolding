"""视觉语言模型服务 — Qwen3-VL-Flash 负责 OCR 增强与图像描述。

通过阿里云 DashScope 的 OpenAI 兼容接口调用。
用于替代/补充 PaddleOCR：对复杂版面、艺术字、屏幕截图的识别能力更强。
"""

from __future__ import annotations

import base64
from typing import Any

from loguru import logger

from src.core.config import get_settings


class VLMService:
    """Qwen3-VL-Flash 多模态服务（单例）。"""

    _instance: VLMService | None = None
    _client: Any = None
    _enabled: bool = False
    _model: str = "qwen3-vl-flash"

    def __new__(cls) -> VLMService:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._client = None
            cls._instance._enabled = False
            cls._instance._model = "qwen3-vl-flash"
        return cls._instance

    def _lazy_init(self) -> None:
        if self._client is not None:
            return
        settings = get_settings()
        self._enabled = settings.vlm_enabled
        if not self._enabled:
            return
        api_key = settings.dashscope_api_key.get_secret_value()
        if not api_key:
            logger.warning("DASHSCOPE_API_KEY 未配置，VLM 增强 OCR 将不启用")
            self._enabled = False
            return
        try:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=api_key,
                base_url=settings.dashscope_api_base,
                timeout=30.0,
            )
            self._model = settings.vlm_model
            logger.info(f"VLM 服务已初始化 | model={self._model}")
        except Exception as e:
            logger.error(f"VLM 客户端初始化失败: {e}")
            self._enabled = False

    @property
    def enabled(self) -> bool:
        self._lazy_init()
        return self._enabled and self._client is not None

    def chat_with_image(
        self, prompt: str, image_bytes: bytes, ext: str = "png", max_tokens: int = 2048,
    ) -> tuple[str, str | None]:
        """用自定义 prompt 与 VLM 对话（附带图片）。

        Returns:
            (回复文本, 错误信息)。成功时 error 为 None。
        """
        self._lazy_init()
        if not self._enabled or not self._client:
            return "", "VLM 服务未启用"

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _ext_to_mime(ext)

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                max_tokens=max_tokens,
                temperature=0.1,
            )
            text = resp.choices[0].message.content or ""
            logger.info(f"VLM chat_with_image 完成 | 字符数: {len(text)}")
            return text, None
        except Exception as e:
            _detail = f"{type(e).__name__}: {e}"
            logger.warning(f"VLM chat_with_image 失败: {_detail}")
            return "", _detail

    def ocr_image(self, image_bytes: bytes, ext: str = "png") -> tuple[str, str | None]:
        """用 VLM 提取图片中的文字。

        Returns:
            (识别文本, 错误信息)。文本为空时 error 非 None。
        """
        self._lazy_init()
        if not self._enabled or not self._client:
            return "", "VLM 服务未启用"

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _ext_to_mime(ext)

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "请仔细提取并输出这张图片中的所有文字内容。"
                                "保持原有的排版结构（段落、换行、缩进）。"
                                "如果图片中没有文字，请回复「无文字」。"
                            ),
                        },
                    ],
                }],
                max_tokens=2048,
                temperature=0.1,
            )
            text = resp.choices[0].message.content or ""
            logger.info(f"VLM OCR 完成 | 字符数: {len(text)}")
            return text, None
        except Exception as e:
            _detail = f"{type(e).__name__}: {e}"
            logger.warning(f"VLM OCR 调用失败: {_detail}")
            return "", _detail

    def extract_tables(
        self, image_bytes: bytes, ext: str = "png"
    ) -> tuple[list[list[list[str]]], str | None]:
        """用 VLM 从 PDF 页面图片中提取表格。

        返回与 pdfplumber 兼容的格式：[[表头], [数据行1], [数据行2], ...]
        """
        self._lazy_init()
        if not self._enabled or not self._client:
            return [], "VLM 服务未启用"

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _ext_to_mime(ext)

        prompt = (
            "请查看这张PDF页面图片，找出其中所有的表格(table)，用Markdown格式输出。\n\n"
            "对每个表格按此格式输出：\n"
            "| 列1标题 | 列2标题 | 列3标题 |\n"
            "| --- | --- | --- |\n"
            "| 数据1 | 数据2 | 数据3 |\n\n"
            "规则：\n"
            "1. 保持每个单元格原始文本完整，不要总结或改写\n"
            "2. 合并单元格请展开为独立单元格\n"
            "3. 如果页面没有任何表格，只回复 NO_TABLES\n"
            "4. 多个表格之间用 ---TABLE--- 分隔（独占一行）"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                max_tokens=4096,
                temperature=0.1,
            )
            text = resp.choices[0].message.content or ""
            logger.info(f"VLM 表格提取原始响应 | 字符数: {len(text)}")

            if not text.strip() or text.strip().upper() == "NO_TABLES":
                return [], None

            tables = self._parse_markdown_tables(text)
            logger.info(f"VLM 表格提取完成 | 表格数: {len(tables)}")
            return tables, None
        except Exception as e:
            _detail = f"{type(e).__name__}: {e}"
            logger.warning(f"VLM 表格提取失败: {_detail}")
            return [], _detail

    @staticmethod
    def _parse_markdown_tables(text: str) -> list[list[list[str]]]:
        """从 VLM 响应中解析 Markdown 表格，返回与 pdfplumber 兼容的格式。"""
        sections = text.split("---TABLE---")

        tables: list[list[list[str]]] = []
        for section in sections:
            section = section.strip()
            if not section:
                continue

            lines = section.split("\n")
            header: list[str] | None = None
            past_separator = False
            data_rows: list[list[str]] = []

            for line in lines:
                line = line.strip()
                if not line or "|" not in line:
                    continue

                parts = [c.strip() for c in line.split("|")]
                if parts and parts[0] == "":
                    parts = parts[1:]
                if parts and parts[-1] == "":
                    parts = parts[:-1]
                if not parts:
                    continue

                # 分隔线（如 "--- | --- | :---"）
                if all(p.replace("-", "").replace(":", "").strip() == "" for p in parts):
                    past_separator = True
                    continue

                if not past_separator:
                    header = parts
                else:
                    if header and len(parts) == len(header):
                        data_rows.append(parts)

            if header and data_rows:
                tables.append([header] + data_rows)

        return tables

    def detect_table_in_image(
        self, image_bytes: bytes, ext: str = "png"
    ) -> dict | None:
        """检测图片中是否包含表格，若包含则提取为结构化数据。

        返回 dict: {table_html, table_data, is_table_image, table_caption}
        若不是表格图片则返回 None。
        """
        self._lazy_init()
        if not self._enabled or not self._client:
            return None

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _ext_to_mime(ext)

        prompt = (
            "你是一个文档分析专家。请判断这张图片的主要内容是否为表格(table)。\n\n"
            "判断标准：\n"
            "- 如果图片主体是结构化的行列数据（如数据表、统计表、对比表），回答 YES\n"
            "- 如果图片是流程图、架构图、照片、截图中的文字段落等，回答 NO\n\n"
            "如果回答 YES，请用 HTML <table> 格式输出表格，要求：\n"
            "1. 合并单元格用 colspan / rowspan 标注\n"
            "2. 保留所有原始数字和文字，不要省略或改写\n"
            "3. 表头行用 <th> 标签\n\n"
            "严格按以下格式输出，以 ---RESULT--- 独占一行分隔：\n"
            "YES 或 NO\n"
            "---RESULT---\n"
            "[如果是 YES，这里输出表格标题/说明（无则留空）]\n"
            "---RESULT---\n"
            "[如果是 YES，这里输出 HTML <table>...</table>]\n\n"
            "如果回答 NO，则只输出 NO，后面不需要任何内容。"
        )
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                        {"type": "text", "text": prompt},
                    ],
                }],
                max_tokens=4096,
                temperature=0.1,
            )
            text = resp.choices[0].message.content or ""
            logger.info(f"VLM 表格检测响应 | 字符数: {len(text)}")

            parts = text.split("---RESULT---")
            is_table = parts[0].strip().upper() == "YES" if parts else False
            if not is_table:
                return None

            caption = parts[1].strip() if len(parts) > 1 else ""
            html = parts[2].strip() if len(parts) > 2 else ""

            if not html or "<table" not in html.lower():
                return None

            # 从 HTML 解析为二维数组
            table_data = self._html_table_to_data(html)
            logger.info(
                f"VLM 表格检测: 是表格, caption={caption[:60] if caption else '无'}, "
                f"rows={len(table_data)}"
            )
            return {
                "table_html": html,
                "table_data": table_data,
                "is_table_image": True,
                "table_caption": caption or None,
            }
        except Exception as e:
            logger.warning(f"VLM 表格检测调用失败: {type(e).__name__}: {e}")
            return None

    @staticmethod
    def _html_table_to_data(html: str) -> list[list[str]]:
        """从 HTML table 提取为二维数组（尽量展开 colspan/rowspan）。"""
        import re
        from html.parser import HTMLParser

        class _TableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.rows: list[list[str]] = []
                self._cur_row: list[str] = []
                self._cur_cell = ""
                self._in_cell = False
                self._colspan = 1

            def handle_starttag(self, tag, attrs):
                if tag in ("th", "td"):
                    self._in_cell = True
                    self._cur_cell = ""
                    attrs_d = dict(attrs)
                    self._colspan = int(attrs_d.get("colspan", 1))
                elif tag == "tr":
                    self._cur_row = []

            def handle_endtag(self, tag):
                if tag in ("th", "td"):
                    self._in_cell = False
                    cell_text = re.sub(r"\s+", " ", self._cur_cell).strip()
                    self._cur_row.append(cell_text)
                    for _ in range(self._colspan - 1):
                        self._cur_row.append("")
                elif tag == "tr":
                    if self._cur_row:
                        self.rows.append(self._cur_row)

            def handle_data(self, data):
                if self._in_cell:
                    self._cur_cell += data

        parser = _TableParser()
        try:
            parser.feed(html)
        except Exception:
            return []
        return parser.rows

    def describe_image(
        self, image_bytes: bytes, ext: str = "png"
    ) -> tuple[str, str | None]:
        """用 VLM 生成图片自然语言描述（用于 RAG 检索增强）。

        Returns:
            (图片描述, 错误信息)。
        """
        self._lazy_init()
        if not self._enabled or not self._client:
            return "", "VLM 服务未启用"

        # 先分类图片类型，再用专用 prompt 描述
        img_type = self._classify_image_type(image_bytes, ext)
        prompt = _IMAGE_TYPE_PROMPTS.get(img_type, _IMAGE_TYPE_PROMPTS["general"])

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _ext_to_mime(ext)

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
                max_tokens=1024,
                temperature=0.3,
            )
            desc = resp.choices[0].message.content or ""
            logger.info(f"VLM 图像描述完成 | type={img_type} | 字符数: {len(desc)}")
            return desc, None
        except Exception as e:
            _detail = f"{type(e).__name__}: {e}"
            logger.warning(f"VLM 图像描述调用失败: {_detail}")
            return "", _detail

    def _classify_image_type(self, image_bytes: bytes, ext: str) -> str:
        """快速分类图片类型，用于选择专用描述 prompt。"""
        self._lazy_init()
        if not self._enabled or not self._client:
            return "general"

        b64 = base64.b64encode(image_bytes).decode("utf-8")
        mime = _ext_to_mime(ext)

        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "请用一个英文单词分类这张图片的类型：\n"
                                "flowchart（流程图）、architecture（架构图）、gantt（甘特图）、"
                                "table（表格）、chart（图表/统计图）、screenshot（截图）、"
                                "photo（照片/实物图）、formula（公式）、general（其他）\n"
                                "只回复一个单词。"
                            ),
                        },
                    ],
                }],
                max_tokens=16,
                temperature=0.0,
            )
            result = (resp.choices[0].message.content or "").strip().lower()
            valid = {
                "flowchart", "architecture", "gantt", "table",
                "chart", "screenshot", "photo", "formula", "general",
            }
            return result if result in valid else "general"
        except Exception:
            return "general"


def _ext_to_mime(ext: str) -> str:
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "bmp": "image/bmp",
        "tiff": "image/tiff",
        "tif": "image/tiff",
        "webp": "image/webp",
    }.get(ext.lower().lstrip("."), "image/png")


# ── 图片类型专用描述 prompt ─────────────────────────────────

_IMAGE_TYPE_PROMPTS: dict[str, str] = {
    "flowchart": (
        "请详细描述这张流程图的内容：\n"
        "1. 流程的起点、终点和主要步骤\n"
        "2. 判断/分支节点及其条件\n"
        "3. 各步骤之间的流转关系\n"
        "4. 涉及的实体/角色/系统\n"
        "用结构化中文描述，便于检索。"
    ),
    "architecture": (
        "请详细描述这张架构图/系统设计图的内容：\n"
        "1. 图中包含哪些组件/模块/服务\n"
        "2. 各组件之间的调用/依赖/数据流关系\n"
        "3. 分层结构（如前端、后端、数据层等）\n"
        "4. 使用的技术栈或协议（如有标注）\n"
        "用结构化中文描述，便于检索。"
    ),
    "gantt": (
        "请详细描述这张甘特图/时间线图的内容：\n"
        "1. 项目的阶段和任务分解\n"
        "2. 各任务的时间起止点\n"
        "3. 任务间的依赖关系\n"
        "4. 里程碑节点\n"
        "用结构化中文描述，便于检索。"
    ),
    "table": (
        "请提取表格中的所有数据，按行列格式描述：\n"
        "1. 表格标题和主题\n"
        "2. 表头各列的含义\n"
        "3. 关键数据行及其含义\n"
        "保持数据的完整性和准确性。"
    ),
    "chart": (
        "请详细描述这张数据图表的内容：\n"
        "1. 图表类型和主题\n"
        "2. 各数据系列的含义\n"
        "3. 关键数据点和趋势\n"
        "4. 坐标轴标签和单位\n"
        "用简洁中文描述关键发现。"
    ),
    "screenshot": (
        "请描述这张截图/界面截图的内容：\n"
        "1. 这是什么软件/系统的界面\n"
        "2. 界面中的主要元素（菜单、按钮、输入框等）\n"
        "3. 展示了什么功能或操作\n"
        "4. 可见的关键文本或数据\n"
        "用简洁中文描述。"
    ),
    "photo": (
        "请用简洁中文描述这张照片的内容：\n"
        "1. 照片拍摄的对象/场景\n"
        "2. 关键细节和特征\n"
        "3. 照片传达的信息或用途\n"
    ),
    "formula": (
        "请提取这张图片中的数学公式，输出为 LaTeX 格式：\n"
        "1. 行间公式用 $$...$$ 包裹\n"
        "2. 行内公式用 $...$ 包裹\n"
        "3. 如有公式编号，附在公式后\n"
        "如果图片中没有公式，回复「无公式」。"
    ),
    "general": (
        "请用简洁中文描述这张图片的主要内容、类型和关键信息。"
        "包含图中可见的文字、图形元素、结构关系等。"
    ),
}

# 全局单例
_vlm: VLMService | None = None


def get_vlm_service() -> VLMService:
    global _vlm
    if _vlm is None:
        _vlm = VLMService()
    return _vlm
