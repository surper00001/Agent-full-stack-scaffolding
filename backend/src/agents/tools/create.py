"""L2 创作工具 — 视频脚本、分镜、拍摄清单、选题分析。"""

from __future__ import annotations

import json

from langchain_core.tools import tool


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


