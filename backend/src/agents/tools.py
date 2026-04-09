"""
Agent 工具集。

定义 Agent 可调用的工具函数（LangChain Tool 格式），
包括搜索、计算、数据库查询等基础工具，
业务方可按此模式扩展自定义工具。
"""

import json
import math
from typing import Any

from langchain_core.tools import tool
from loguru import logger


# ---- 基础工具 ----
@tool
def calculator(expression: str) -> str:
    """
    安全数学计算器，支持 + - * / ** sqrt() abs() 等基本运算。

    Args:
        expression: 数学表达式字符串，例如 "2 + 3 * 4"

    Returns:
        计算结果字符串
    """
    # 白名单安全执行
    allowed_names = {
        "abs": abs,
        "round": round,
        "max": max,
        "min": min,
        "sqrt": math.sqrt,
        "pow": pow,
        "log": math.log,
        "pi": math.pi,
        "e": math.e,
    }
    try:
        result = eval(expression, {"__builtins__": {}}, allowed_names)
        logger.info(f"计算器: {expression} = {result}")
        return str(result)
    except Exception as e:
        return f"计算错误: {e}"


@tool
def text_length(text: str) -> str:
    """
    统计文本的字符数和词数。

    Args:
        text: 待统计的文本

    Returns:
        包含字符数和词数的字符串
    """
    char_count = len(text)
    word_count = len(text.split())
    return f"字符数: {char_count}, 词数: {word_count}"


@tool
def current_time() -> str:
    """获取当前 UTC 时间（ISO 格式）。"""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


# ---- 扩展工具占位 ----
# 业务方可在此添加自定义工具，例如：
# - 查询数据库
# - 调用外部 API
# - 文件操作
# - 发送通知
# 示例:
# @tool
# def search_knowledge_base(query: str) -> str:
#     """搜索知识库。"""
#     ...


def get_default_tools() -> list[Any]:
    """获取 Agent 默认加载的工具列表。"""
    return [calculator, text_length, current_time]


__all__ = ["calculator", "text_length", "current_time", "get_default_tools"]
