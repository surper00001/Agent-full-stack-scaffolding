"""L3 输出工具 — 文件保存与下载。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from langchain_core.tools import tool
from loguru import logger

from src.core.config import get_settings

_OUTPUT_DIR = Path(get_settings().file_output_dir)
_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _save_and_get_url(content: str, suffix: str, mime: str) -> str:
    """保存文件并返回下载信息。"""
    file_id = uuid.uuid4().hex[:12]
    filename = f"{file_id}{suffix}"
    filepath = _OUTPUT_DIR / filename
    filepath.write_text(content, encoding="utf-8")
    settings = get_settings()
    download_url = f"{settings.file_download_url_prefix}/{filename}"
    size_bytes = len(content.encode("utf-8"))
    logger.info(f"文件已保存: {filepath} ({size_bytes} bytes)")
    return json.dumps({
        "filename": filename,
        "download_url": download_url,
        "mime_type": mime,
        "size_bytes": size_bytes,
        "size_display": f"{size_bytes / 1024:.1f} KB" if size_bytes > 1024 else f"{size_bytes} B",
        "message": "文件已生成，可通过 download_url 下载",
    }, ensure_ascii=False)


@tool
def save_markdown_file(content: str, title: str = "output") -> str:
    """
    将 Markdown 内容保存为 .md 文件，返回下载链接。
    当需要输出脚本、方案、报告等文档时使用此工具。

    Args:
        content: Markdown 格式的完整内容
        title: 文件标题（不含扩展名）
    """
    safe_title = "".join(c for c in title if c.isalnum() or c in "._- ")[:80].strip()
    full = f"# {safe_title}\n\n{content}" if not content.startswith("#") else content
    return _save_and_get_url(full, ".md", "text/markdown")


@tool
def save_text_file(content: str) -> str:
    """
    将纯文本内容保存为 .txt 文件，返回下载链接。
    适用于字幕文件、纯文本脚本等。

    Args:
        content: 纯文本内容
    """
    return _save_and_get_url(content, ".txt", "text/plain")


@tool
def save_srt_subtitle(subtitles_json: str) -> str:
    """
    将 JSON 格式字幕数据转换为 SRT 字幕文件并保存，返回下载链接。
    输入的 JSON 格式：[{"index":1,"start":"00:00:01,000","end":"00:00:04,000","text":"字幕内容"},...]

    Args:
        subtitles_json: JSON 字符串，包含字幕数组
    """
    try:
        items = json.loads(subtitles_json)
        if not isinstance(items, list):
            return "错误：请输入 JSON 数组格式的字幕数据"
        srt_lines = []
        for sub in items:
            srt_lines.append(str(sub.get("index", len(srt_lines) // 4 + 1)))
            srt_lines.append(f"{sub['start']} --> {sub['end']}")
            srt_lines.append(sub.get("text", ""))
            srt_lines.append("")
        return _save_and_get_url("\n".join(srt_lines), ".srt", "text/plain")
    except (json.JSONDecodeError, KeyError) as e:
        return f"字幕数据解析失败: {e}"


