"""
Agent 工具集 — 专业视频创作工具链。

工具分层：
  L0: 基础工具（计算、时间）
  L1: 信息获取（Web 搜索、知识检索）
  L2: 创作工具（脚本、分镜、拍摄清单、文案）
  L3: 输出工具（Markdown/TXT 文件生成 → 下载链接）
  Meta: 工具发现（tool_search）
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from langchain_core.tools import tool
from loguru import logger

from src.core.config import get_settings

# ============================================================
# L0 — 基础工具
# ============================================================

@tool
def calculator(expression: str) -> str:
    """
    安全数学计算器。支持 + - * / ** sqrt() abs() log() round() max() min() pow() 及常量 pi, e。

    Args:
        expression: 数学表达式，如 "sqrt(16) + 2 * pi"
    """
    allowed_names = {
        "abs": abs, "round": round, "max": max, "min": min,
        "sqrt": math.sqrt, "pow": pow, "log": math.log,
        "pi": math.pi, "e": math.e,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        logger.info(f"计算器: {expression} = {result}")
        return str(result)
    except Exception as e:
        return f"计算错误: {e}"


@tool
def current_time() -> str:
    """获取当前 UTC 时间（ISO 格式），同时返回中文可读格式。"""
    now = datetime.now(UTC)
    return json.dumps({
        "utc": now.isoformat(),
        "cn_readable": now.strftime("%Y年%m月%d日 %H:%M UTC"),
    }, ensure_ascii=False)


# ============================================================
# L1 — 信息获取
# ============================================================

def _extract_bocha_web_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    """从博查 API 响应提取网页列表（兼容 data.webPages.value 与顶层 webPages）。"""
    web_pages = data.get("data", {}).get("webPages") or data.get("webPages")
    if web_pages is None:
        return []
    if isinstance(web_pages, list):
        return web_pages
    if isinstance(web_pages, dict):
        value = web_pages.get("value")
        if isinstance(value, list):
            return value
    return []


@tool
def web_search(query: str, count: int = 5) -> str:
    """
    使用博查搜索引擎搜索互联网，获取最新信息、热点话题、行业知识。
    适用于：市场调研、热点追踪、素材搜集、事实核查。

    Args:
        query: 搜索关键词
        count: 返回结果数量，默认 5，最大 10
    """
    settings = get_settings()
    api_key = settings.bocha_api_key.get_secret_value()
    if not api_key:
        return "博查搜索 API Key 未配置，请联系管理员设置 BOCHA_API_KEY。"

    try:
        resp = httpx.post(
            settings.bocha_api_base,
            json={
                "query": query,
                "count": min(count, 10),
                "summary": True,
                "freshness": "noLimit",
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for item in _extract_bocha_web_items(data)[:count]:
            results.append({
                "title": item.get("name", ""),
                "url": item.get("url", ""),
                "snippet": item.get("snippet") or item.get("summary", ""),
            })

        if not results:
            return f"未找到与“{query}”相关的结果。"

        return json.dumps({"query": query, "results": results}, ensure_ascii=False, indent=2)
    except httpx.TimeoutException:
        logger.warning(f"Web 搜索超时: query={query!r}")
        return f"搜索“{query}”超时，请稍后重试。"
    except httpx.HTTPStatusError as e:
        logger.error(
            f"Web 搜索 HTTP 错误: {e.response.status_code} | url={settings.bocha_api_base}"
        )
        return f"搜索失败: HTTP {e.response.status_code}（请检查 BOCHA_API_BASE 与 API Key）"
    except Exception as e:
        logger.error(f"Web 搜索失败: {e}")
        return f"搜索失败: {e}"


# ============================================================
# L2 — 创作工具
# ============================================================

@tool
def generate_video_script(
    topic: str,
    style: str = "professional",
    target_audience: str = "通用",
    duration_seconds: int = 60,
    platform: str = "抖音",
) -> str:
    """
    生成短视频脚本。根据主题、风格、受众和平台特征，输出包含口播文案、画面描述、时长的完整脚本。

    Args:
        topic: 视频主题，如 "AI 如何改变视频创作"
        style: 风格 — professional(专业), casual(轻松), dramatic(剧情), educational(教学)
        target_audience: 目标受众描述
        duration_seconds: 视频时长（秒）
        platform: 发布平台 — 抖音/视频号/B站/YouTube/TikTok
    """
    platform_tips = {
        "抖音": "前3秒黄金开头，强节奏感，口语化，配合热梗",
        "视频号": "偏成熟受众，内容有深度，叙事节奏稍慢",
        "B站": "可以更长更深，允许中二/玩梗，弹幕互动强",
        "YouTube": "结构完整，开场有hook，中段有干货，结尾有CTA",
        "TikTok": "快节奏，视觉冲击，英文优先，trending sound配合",
    }

    style_prompt_map = {
        "professional": "专业严谨，数据支撑，逻辑清晰",
        "casual": "轻松口语化，像朋友聊天，有亲和力",
        "dramatic": "设置悬念，情绪起伏，故事性叙事",
        "educational": "循序渐进，举例说明，易于理解",
    }

    # 这个工具返回结构化的脚本模板，实际内容由 Agent LLM 填充
    script_template = {
        "topic": topic,
        "style": style,
        "platform": platform,
        "duration_seconds": duration_seconds,
        "platform_advice": platform_tips.get(platform, ""),
        "style_advice": style_prompt_map.get(style, ""),
        "structure": {
            "hook": {"duration_sec": 5, "description": "开头黄金3-5秒，吸引注意力"},
            "intro": {"duration_sec": 10, "description": "引出主题，建立预期"},
            "main_body": {"duration_sec": duration_seconds - 30, "description": "核心内容，分2-3个要点"},
            "climax": {"duration_sec": 10, "description": "高潮/转折/金句"},
            "cta": {"duration_sec": 5, "description": "引导点赞/关注/评论/转发"},
        },
        "instruction": f"请根据以上结构生成完整的视频脚本。每个部分需要：(1) 口播文案 (2) 画面描述 (3) 建议时长。目标受众：{target_audience}。",
    }
    return json.dumps(script_template, ensure_ascii=False, indent=2)


@tool
def generate_storyboard(
    script_content: str,
    shot_count: int = 8,
    aspect_ratio: str = "9:16",
) -> str:
    """
    根据脚本生成分镜脚本。每个镜头包含画面构图、运镜方式、字幕内容和参考时长。

    Args:
        script_content: 完整的视频脚本文本
        shot_count: 分镜数量
        aspect_ratio: 画幅比例 — 9:16(竖屏) / 16:9(横屏) / 1:1(方形)
    """
    template = {
        "aspect_ratio": aspect_ratio,
        "total_shots": shot_count,
        "storyboard": [
            {
                "shot_number": i + 1,
                "scene_description": f"镜头{i + 1}画面描述",
                "camera_movement": "固定/推/拉/摇/移/跟/升/降",
                "composition": "构图方式（中心/三分/对称/引导线）",
                "dialogue_or_voiceover": "台词或旁白内容",
                "text_overlay": "字幕/花字内容",
                "duration_sec": 5,
                "transition": "切/淡入淡出/滑动/缩放",
            }
            for i in range(shot_count)
        ],
        "instruction": f"请根据以下脚本，为每个镜头填充具体内容：\n\n{script_content[:2000]}",
    }
    return json.dumps(template, ensure_ascii=False, indent=2)


@tool
def generate_shot_list(
    scene_description: str,
    format_type: str = "detailed",
) -> str:
    """
    生成拍摄清单。适合实际拍摄时的现场参考，包含景别、机位、灯光、道具等。

    Args:
        scene_description: 场景描述
        format_type: detailed(详细) / simple(简要)
    """
    checklist = {
        "scene": scene_description[:500],
        "format": format_type,
        "checklist": {
            "camera": {
                "primary_angle": "主角度",
                "lens": "镜头焦段建议",
                "aperture": "光圈建议",
                "white_balance": "白平衡",
                "fps": "帧率（24/30/60）",
            },
            "lighting": {
                "key_light": "主光源位置与类型",
                "fill_light": "辅光",
                "back_light": "轮廓光",
                "practical": "环境光源",
            },
            "audio": {
                "mic_type": "麦克风类型",
                "position": "收音位置",
                "ambient": "环境音注意",
            },
            "props": ["道具清单"],
            "wardrobe": "服装建议",
            "notes": "特殊注意事项",
        },
    }
    return json.dumps(checklist, ensure_ascii=False, indent=2)


@tool
def analyze_trending_topics(
    keyword: str = "",
    category: str = "general",
) -> str:
    """
    分析热门话题/爆款选题。搜索当前热门内容并提供创作建议。
    先使用 web_search 获取信息，再调用此工具分析。

    Args:
        keyword: 话题关键词，留空则分析当前通用热点
        category: 分类 — general/video/tech/entertainment/education
    """
    categories = {
        "video": "短视频创作趋势、爆款公式、剪辑技巧",
        "tech": "科技数码、AI应用、软件开发",
        "entertainment": "影视综、音乐、明星动态",
        "education": "知识科普、技能教学、考证考级",
        "general": "综合热点、社会话题、生活技巧",
    }
    return json.dumps({
        "keyword": keyword or "当前热点",
        "category": categories.get(category, categories["general"]),
        "analysis_dimensions": [
            "热度指数", "受众画像", "内容形式建议",
            "差异化切入点", "标题/封面建议", "发布时间建议",
        ],
        "instruction": "请基于 web_search 搜索结果，从以上维度进行分析，给出 3-5 个具体选题建议。",
    }, ensure_ascii=False, indent=2)


# ============================================================
# L3 — 文件输出工具
# ============================================================

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


# ============================================================
# L1 — 知识库检索（动态注册，需要 DB session）
# ============================================================

_KB_SEARCH_TOOL_NAME = "search_knowledge_base"


def _build_kb_search_description(kb_names: list[str]) -> str:
    """构建 KB 搜索工具的描述文本。"""
    kb_list = "、".join(kb_names) if kb_names else "用户的知识库"
    return (
        f"搜索用户的知识库（{kb_list}）中的文档内容。"
        "当用户的问题涉及已有文档、需要查找内部资料、询问项目相关内容时使用此工具。"
        "支持自然语言查询，返回最相关的文档片段及其来源信息。\n\n"
        "Args:\n"
        "    query: 自然语言搜索查询，如 \"JWT 认证流程\" 或 \"API 接口文档\"\n"
        "    top_k: 返回结果数量，默认 5，最大 10\n\n"
        "Returns: JSON 格式的搜索结果，包含 content（内容）、source（来源文件）、"
        "page（页码）、score（匹配分数 0-1）、chunk_id（分块ID）"
    )


def create_kb_search_tool(
    tenant_id: str,
    kb_ids: list[str],
    kb_names: list[str] | None = None,
) -> Any:
    """创建一个绑定到指定知识库的搜索工具。

    采用工厂模式：每次对话创建 Agent 时，根据用户选择的知识库动态构建工具。
    工具内部通过独立的 DB session 访问知识库服务。

    Args:
        tenant_id: 租户 ID
        kb_ids: 用户选择的知识库 ID 列表
        kb_names: 知识库名称列表（用于工具描述）

    Returns:
        绑定到指定知识库的 langchain Tool
    """
    if not kb_ids:
        raise ValueError("kb_ids 不能为空")

    display_names = kb_names or [f"知识库{i+1}" for i in range(len(kb_ids))]
    desc = _build_kb_search_description(display_names)

    @tool
    def search_knowledge_base(query: str, top_k: int = 5) -> str:
        """搜索用户的知识库。Agent 在需要查找文档资料时自动调用。"""
        import asyncio

        from src.db.session import AsyncSessionLocal
        from src.services.knowledge_base_service import KnowledgeBaseService

        async def _search() -> str:
            from src.services.rag.context_builder import search_multiple_kbs

            async with AsyncSessionLocal() as session:
                kb_svc = KnowledgeBaseService(session)
                top, context_text, _ = await search_multiple_kbs(
                    kb_svc=kb_svc,
                    kb_ids=kb_ids,
                    tenant_id=tenant_id,
                    query=query,
                    top_k=min(top_k, 10),
                    rerank=True,
                )

            if not top:
                return json.dumps({
                    "query": query,
                    "total_found": 0,
                    "results": [],
                    "hint": "知识库中未找到相关内容，建议使用 web_search 搜索互联网或请用户提供更多信息。",
                }, ensure_ascii=False)

            results = [
                {
                    "content": c.content,
                    "source": c.source,
                    "page": c.page,
                    "score": c.score,
                    "chunk_id": c.chunk_id,
                    "chunk_type": c.chunk_type,
                    "section_title": c.section_title,
                }
                for c in top
            ]

            return json.dumps({
                "query": query,
                "total_found": len(results),
                "returned": len(results),
                "results": results,
                "context_for_llm": context_text,
            }, ensure_ascii=False, indent=2)

        # 在同步上下文中运行异步搜索
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, _search())
                    return future.result(timeout=30)
            return asyncio.run(_search())
        except RuntimeError:
            return asyncio.run(_search())
        except Exception as e:
            logger.error(f"知识库搜索异常: {e}")
            return json.dumps({
                "query": query,
                "error": str(e),
                "results": [],
            }, ensure_ascii=False)

    # 覆盖工具名和描述
    search_knowledge_base.name = _KB_SEARCH_TOOL_NAME
    search_knowledge_base.description = desc

    return search_knowledge_base


# ============================================================
# Meta — 工具发现
# ============================================================

# 全局工具注册表，在模块加载时填充
_tool_registry: dict[str, dict[str, Any]] = {}


def register_tool_meta(t: Any) -> None:
    """将工具元信息注册到全局注册表。"""
    _tool_registry[t.name] = {
        "name": t.name,
        "description": t.description.split("\n")[0] if t.description else "",
        "full_description": t.description or "",
        "category": _categorize_tool(t.name),
    }


def _categorize_tool(name: str) -> str:
    cats = {
        "calculator": "L0-基础", "current_time": "L0-基础",
        "web_search": "L1-信息", "analyze_trending_topics": "L1-信息",
        "generate_video_script": "L2-创作", "generate_storyboard": "L2-创作",
        "generate_shot_list": "L2-创作",
        "save_markdown_file": "L3-输出", "save_text_file": "L3-输出",
        "save_srt_subtitle": "L3-输出",
        "tool_search": "Meta",
    }
    return cats.get(name, "Unknown")


@tool
def tool_search(query: str = "", category: str = "") -> str:
    """
    搜索当前可用的工具。当不确定该使用哪个工具完成任务时，先调用此工具了解可用选项。
    支持按关键词搜索和按分类过滤。

    Args:
        query: 搜索关键词（模糊匹配工具名和描述），留空返回全部
        category: 分类过滤 — L0-基础/L1-信息/L2-创作/L3-输出
    """
    results = []
    for name, meta in _tool_registry.items():
        if name == "tool_search":
            continue
        q = query.lower()
        if q and q not in name.lower() and q not in meta["description"].lower():
            continue
        if category and meta["category"] != category:
            continue
        results.append({
            "name": meta["name"],
            "description": meta["description"],
            "category": meta["category"],
        })

    if not results:
        return json.dumps({
            "message": f"未找到匹配 '{query}' 的工具",
            "all_categories": ["L0-基础", "L1-信息", "L2-创作", "L3-输出"],
            "hint": "尝试 tool_search(query='') 查看全部工具",
        }, ensure_ascii=False)

    return json.dumps({
        "query": query or "(全部)",
        "count": len(results),
        "tools": results,
    }, ensure_ascii=False, indent=2)


# ============================================================
# 工具集导出
# ============================================================

_ALL_TOOLS = [
    # L0
    calculator,
    current_time,
    # L1
    web_search,
    analyze_trending_topics,
    # L2
    generate_video_script,
    generate_storyboard,
    generate_shot_list,
    # L3
    save_markdown_file,
    save_text_file,
    save_srt_subtitle,
    # Meta
    tool_search,
]

# 初始化注册表
for _t in _ALL_TOOLS:
    register_tool_meta(_t)


def get_default_tools() -> list[Any]:
    """获取 Agent 默认加载的完整工具列表。"""
    return list(_ALL_TOOLS)


def get_tool_registry() -> dict[str, dict[str, Any]]:
    """获取工具注册表（供 Agent 和 ToolNode 使用）。"""
    return dict(_tool_registry)


def get_tools_by_category(category: str) -> list[Any]:
    """按分类获取工具。"""
    return [t for t in _ALL_TOOLS if _categorize_tool(t.name) == category]


__all__ = [
    "calculator", "current_time",
    "web_search", "analyze_trending_topics",
    "generate_video_script", "generate_storyboard", "generate_shot_list",
    "save_markdown_file", "save_text_file", "save_srt_subtitle",
    "tool_search",
    "get_default_tools", "get_tool_registry", "get_tools_by_category",
    "register_tool_meta",
]
