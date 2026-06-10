"""安全模块：JWT 令牌管理 + 密码哈希。

支持 JWT 密钥轮换（kid header）：
- 活跃签名密钥始终为 jwt_secret_key (kid="default")
- 可选配置 jwt_additional_keys 作为备用验证密钥
- 轮换时：将旧密钥加入 jwt_additional_keys，更新 jwt_secret_key
- 旧令牌用旧密钥验证继续有效，新令牌用新密钥签发
"""

import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import bcrypt
from jose import JWTError, jwt

from src.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def _get_key_registry() -> dict[str, str]:
    """获取所有验证密钥映射 (kid → secret)。

    包含:
    - 当前活跃密钥 (kid="default")
    - 配置的附加密钥 (jwt_additional_keys, JSON 格式 [{"kid": "...", "key": "..."}, ...])
    """
    settings = get_settings()
    keys = {"default": settings.jwt_secret_key.get_secret_value()}

    extra_keys = settings.jwt_additional_keys
    if extra_keys:
        try:
            for entry in json.loads(extra_keys):
                if "kid" in entry and "key" in entry:
                    keys[entry["kid"]] = entry["key"]
        except (json.JSONDecodeError, TypeError):
            pass  # 配置格式错误时忽略

    return keys


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> tuple[str, int]:
    """创建 JWT 访问令牌（短有效期），返回 (token, expires_in_seconds)。

    令牌头部包含 kid="default"，指向当前活跃签名密钥。
    """
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    to_encode.update({"exp": expire, "iat": datetime.now(UTC), "type": "access"})
    token = jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        headers={"kid": "default"},
    )
    return token, int((expire - datetime.now(UTC)).total_seconds())


def decode_access_token(token: str) -> dict[str, Any] | None:
    """解码 JWT 令牌，无效或过期返回 None。

    支持多密钥验证：
    1. 从 token header 读取 kid
    2. 从密钥注册表查找对应密钥
    3. 如果 kid 不存在，回退到当前活跃密钥
    """
    settings = get_settings()

    # 尝试从 header 读取 kid
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        return None

    kid = unverified_header.get("kid", "default")
    key_registry = _get_key_registry()
    signing_key = key_registry.get(kid)

    if signing_key is None:
        # kid 未知，尝试用所有已知密钥验证
        for _kid, key in key_registry.items():
            try:
                payload = jwt.decode(
                    token, key, algorithms=[settings.jwt_algorithm],
                )
                if payload.get("type") == "access":
                    return cast("dict[str, Any]", payload)
            except JWTError:
                continue
        return None

    try:
        payload = jwt.decode(
            token, signing_key, algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access":
            return None
        return cast("dict[str, Any]", payload)
    except JWTError:
        return None


def generate_refresh_token() -> tuple[str, str]:
    """生成 Refresh Token（随机字符串 + SHA-256 哈希）。

    Refresh Token 本身已是 256 位高熵随机串，使用 SHA-256 做确定性哈希
    （非 bcrypt），保证刷新时相同输入→相同哈希，可精确查库匹配。
    """
    raw = secrets.token_urlsafe(32)
    token_hash = hash_refresh_token(raw)
    return raw, token_hash


def hash_refresh_token(raw: str) -> str:
    """计算 Refresh Token 的 SHA-256 哈希（确定性，用于查库匹配）。"""
    import hashlib

    return hashlib.sha256(raw.encode()).hexdigest()
