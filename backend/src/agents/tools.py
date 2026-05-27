"""Agent 工具集 — 专业视频创作工具链。

工具分层：
  L0: 基础工具（计算、时间）
  L1: 信息获取（Web 搜索、知识检索）
  L2: 创作工具（脚本、分镜、拍摄清单、文案）
  L3: 输出工具（Markdown/TXT 文件生成 → 下载链接）
  Meta: 工具发现（tool_search）

本文件保留为向后兼容的 re-export 模块，实际实现在 agents/tools/ 子包中。
"""

from src.agents.tools.base import calculator, current_time
from src.agents.tools.create import (
    analyze_trending_topics,
    generate_shot_list,
    generate_storyboard,
    generate_video_script,
)
from src.agents.tools.info import create_kb_search_tool, web_search
from src.agents.tools.meta import (
    get_default_tools,
    get_tool_registry,
    get_tools_by_category,
    register_tool_meta,
    tool_search,
)
from src.agents.tools.mindmap import (
    edit_mindmap,
    export_mindmap,
    fetch_url_outline,
    generate_mindmap,
)
from src.agents.tools.output import save_markdown_file, save_srt_subtitle, save_text_file

__all__ = [
    "calculator",
    "current_time",
    "web_search",
    "create_kb_search_tool",
    "generate_video_script",
    "generate_storyboard",
    "generate_shot_list",
    "analyze_trending_topics",
    "save_markdown_file",
    "save_text_file",
    "save_srt_subtitle",
    "generate_mindmap",
    "edit_mindmap",
    "export_mindmap",
    "fetch_url_outline",
    "tool_search",
    "get_default_tools",
    "get_tool_registry",
    "get_tools_by_category",
    "register_tool_meta",
]
