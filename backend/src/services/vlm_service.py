"""视觉语言模型服务 — Qwen3-VL-Flash 负责 OCR 增强与图像描述。

通过阿里云 DashScope 的 OpenAI 兼容接口调用。
用于替代/补充 PaddleOCR：对复杂版面、艺术字、屏幕截图的识别能力更强。
"""

from __future__ import annotations

import base64

from loguru import logger

from src.core.config import get_settings


class VLMService:
    """Qwen3-VL-Flash 多模态服务（单例）。"""

    _instance: VLMService | None = None

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
            logger.warning(f"VLM OCR 调用失败: {e}")
            return "", str(e)

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
            logger.warning(f"VLM 表格提取失败: {e}")
            return [], str(e)

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
                            "text": "请用一段简洁的中文描述这张图片的主要内容、类型和关键信息。",
                        },
                    ],
                }],
                max_tokens=512,
                temperature=0.3,
            )
            desc = resp.choices[0].message.content or ""
            logger.info(f"VLM 图像描述完成 | 字符数: {len(desc)}")
            return desc, None
        except Exception as e:
            logger.warning(f"VLM 图像描述调用失败: {e}")
            return "", str(e)


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


# 全局单例
_vlm: VLMService | None = None


def get_vlm_service() -> VLMService:
    global _vlm
    if _vlm is None:
        _vlm = VLMService()
    return _vlm
