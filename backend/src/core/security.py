"""安全模块：JWT 令牌管理 + 密码哈希。"""

import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from src.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> tuple[str, int]:
    """创建 JWT 访问令牌（短有效期），返回 (token, expires_in_seconds)。"""
    settings = get_settings()
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        )
    to_encode.update({"exp": expire, "iat": datetime.now(timezone.utc), "type": "access"})
    token = jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, int((expire - datetime.now(timezone.utc)).total_seconds())


def decode_access_token(token: str) -> dict | None:
    """解码 JWT 令牌，无效或过期返回 None。"""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


def generate_refresh_token() -> tuple[str, str]:
    """生成 Refresh Token（随机字符串），返回 (raw_token, token_hash)。"""
    raw = secrets.token_urlsafe(32)
    token_hash = hash_password(raw)
    return raw, token_hash
