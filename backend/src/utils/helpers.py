"""
通用工具函数模块。
"""

import hashlib
import time
import uuid as _uuid
from typing import Any


def generate_uuid() -> str:
    """生成 UUID4 字符串。"""
    return str(_uuid.uuid4())


def generate_short_id(length: int = 12) -> str:
    """生成短 ID（基于时间戳 + 随机数的 hex 截断）。"""
    raw = f"{time.time_ns()}{_uuid.uuid4()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:length]


def safe_get(d: dict[str, Any], key: str, default: Any = None) -> Any:
    """安全从字典取值，键不存在时返回默认值（类型安全包装）。"""
    return d.get(key, default)


def mask_api_key(key: str, visible: int = 4) -> str:
    """脱敏显示 API Key，仅显示首尾若干字符。"""
    if len(key) <= visible * 2:
        return "*" * len(key)
    return f"{key[:visible]}{'*' * (len(key) - visible * 2)}{key[-visible:]}"
