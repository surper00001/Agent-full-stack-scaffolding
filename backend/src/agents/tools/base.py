"""L0 基础工具 — 计算器、时间。"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime

from langchain_core.tools import tool
from loguru import logger


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


