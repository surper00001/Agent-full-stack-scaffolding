"""JWT 密钥轮换测试。

测试 kid header 注入、多密钥验证、密钥注册表。
"""

from __future__ import annotations

import json

import pytest

from src.core.security import (
    _get_key_registry,
    create_access_token,
    decode_access_token,
)


class TestJWTKidHeader:
    """测试 JWT 令牌携带 kid header。"""

    def test_token_contains_kid_header(self):
        """创建的令牌 header 应包含 kid="default"。"""
        from jose import jwt as jose_jwt

        token, _ = create_access_token({"sub": "test-user"})
        header = jose_jwt.get_unverified_header(token)
        assert header.get("kid") == "default", f"Header 应包含 kid=default, got={header}"


class TestJWTKeyRegistry:
    """测试多密钥注册表。"""

    def test_default_key_always_present(self):
        """密钥注册表至少包含 'default' 键。"""
        registry = _get_key_registry()
        assert "default" in registry
        assert len(registry["default"]) > 0

    def test_registry_returns_string_keys(self):
        """注册表中的密钥应为字符串。"""
        registry = _get_key_registry()
        for kid, key in registry.items():
            assert isinstance(key, str), f"kid={kid} 的密钥应为 str"
            assert len(key) > 0, f"kid={kid} 的密钥不应为空"


class TestJWTSignVerify:
    """测试签名→验证往返。"""

    def test_sign_and_verify_roundtrip(self):
        """使用默认密钥签名和验证应成功。"""
        data = {"sub": "user-123", "role": "admin"}
        token, expires_in = create_access_token(data)
        assert expires_in > 0
        payload = decode_access_token(token)
        assert payload is not None
        assert payload["sub"] == "user-123"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_tampered_token_returns_none(self):
        """被篡改的令牌应返回 None。"""
        token, _ = create_access_token({"sub": "user-123"})
        tampered = token[:-5] + "XXXXX"
        payload = decode_access_token(tampered)
        assert payload is None

    def test_wrong_type_token_rejected(self):
        """type 不是 'access' 的令牌应被拒绝。"""
        from datetime import UTC, datetime, timedelta
        from jose import jwt as jose_jwt
        from src.core.config import get_settings

        settings = get_settings()
        payload = {
            "sub": "test",
            "exp": datetime.now(UTC) + timedelta(minutes=5),
            "type": "refresh",  # 错误的 type
        }
        token = jose_jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            headers={"kid": "default"},
        )
        result = decode_access_token(token)
        assert result is None, "type=refresh 应被拒绝"


class TestJWTExpiredToken:
    """测试过期令牌处理。"""

    def test_expired_token_returns_none(self):
        """过期令牌应返回 None。"""
        from datetime import UTC, datetime, timedelta
        from jose import jwt as jose_jwt
        from src.core.config import get_settings

        settings = get_settings()
        payload = {
            "sub": "test",
            "exp": datetime.now(UTC) - timedelta(minutes=1),  # 已过期
            "type": "access",
        }
        token = jose_jwt.encode(
            payload,
            settings.jwt_secret_key.get_secret_value(),
            algorithm=settings.jwt_algorithm,
            headers={"kid": "default"},
        )
        result = decode_access_token(token)
        assert result is None, "过期令牌应返回 None"
