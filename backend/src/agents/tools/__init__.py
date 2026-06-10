"""Agent 工具集 - 专业视频创作工具链。

工具分层：
  L0: 基础工具（计算、时间）
  L1: 信息获取（Web 搜索、知识检索）
  L2: 创作工具（脚本、分镜、拍摄清单、文案）
  L3: 输出工具（Markdown/TXT 文件生成 → 下载链接）
  Meta: 工具发现（tool_search）

⚠ 所有工具现在通过 UnifiedToolRegistry 统一管理。
  HarnessTool（file_tools, shell_tool, network_tools）在启动时由
  bootstrap.py → setup_harness_tools() → register_builtin_tools() 注册。
  LangChain @tool 在模块加载时注册到统一注册表。
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
from src.agents.tools.mindmap import (
    edit_mindmap,
    export_mindmap,
    fetch_url_outline,
    generate_mindmap,
)
from src.agents.tools.output import save_markdown_file, save_srt_subtitle, save_text_file
from src.agents.tools.resume import generate_cover_letter_docx, generate_resume_docx

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
    generate_mindmap,
    edit_mindmap,
    export_mindmap,
    fetch_url_outline,
    tool_search,
    generate_resume_docx,
    generate_cover_letter_docx,
]

# 初始化注册表 — 将所有 LangChain @tool 注册到统一注册表
_init_registry(_ALL_TOOLS)

# 全局注册 KBSearchHarnessTool（HarnessTool 体系）
# 具体 KB 绑定在每次对话时通过 set_binding() 动态设置
from src.harness.unified_registry import get_unified_registry

try:
    _kb_harness = get_unified_registry().get_harness_tool("search_knowledge_base")
    if _kb_harness is None:
        from src.agents.tools.kb_search import KBSearchHarnessTool
        get_unified_registry().register(KBSearchHarnessTool(), source="builtin")
except Exception:
    pass  # 静默失败，KB 搜索在首次 create_kb_search_tool() 时懒注册

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
    "generate_resume_docx",
    "generate_cover_letter_docx",
    "get_default_tools",
    "get_tool_registry",
    "get_tools_by_category",
    "register_tool_meta",
]
