"""Agent 工具集 - 专业视频创作工具链。

工具分层：
  L0: 基础工具（计算、时间）
  L1: 信息获取（Web 搜索、知识检索）
  L2: 创作工具（脚本、分镜、拍摄清单、文案）
  L3: 输出工具（Markdown/TXT 文件生成 → 下载链接）
  Meta: 工具发现（tool_search）
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
    _init_registry,
    get_default_tools,
    get_tool_registry,
    get_tools_by_category,
    register_tool_meta,
    tool_search,
)
from src.agents.tools.output import save_markdown_file, save_srt_subtitle, save_text_file

# 组装完整工具列表
_ALL_TOOLS = [
    calculator,
    current_time,
    web_search,
    analyze_trending_topics,
    generate_video_script,
    generate_storyboard,
    generate_shot_list,
    save_markdown_file,
    save_text_file,
    save_srt_subtitle,
    tool_search,
]

# 初始化注册表
_init_registry(_ALL_TOOLS)

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
    "tool_search",
    "get_default_tools",
    "get_tool_registry",
    "get_tools_by_category",
    "register_tool_meta",
]
