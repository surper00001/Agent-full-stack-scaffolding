"""Query Rewriter 单元测试。"""

import pytest

from src.services.rag.query_rewriter import (
    _looks_already_rewritten,
    rewrite_query,
    should_rewrite,
)


class TestShouldRewrite:
    """should_rewrite 逻辑测试。"""

    def test_short_query_triggers_rewrite(self, monkeypatch):
        """短 query 应触发改写。"""
        monkeypatch.setattr(
            "src.services.rag.query_rewriter.get_settings",
            lambda: _fake_settings(rewrite_enabled=True, min_chars=20),
        )
        assert should_rewrite("怎么配置") is True

    def test_long_query_skips_rewrite(self, monkeypatch):
        """长 query 不触发改写。"""
        monkeypatch.setattr(
            "src.services.rag.query_rewriter.get_settings",
            lambda: _fake_settings(rewrite_enabled=True, min_chars=20),
        )
        assert should_rewrite("JWT 令牌的过期时间是多长，如何配置刷新策略") is False

    def test_disabled_skips_rewrite(self, monkeypatch):
        """禁用时跳过改写。"""
        monkeypatch.setattr(
            "src.services.rag.query_rewriter.get_settings",
            lambda: _fake_settings(rewrite_enabled=False, min_chars=20),
        )
        assert should_rewrite("怎么配置") is False

    def test_already_rewritten_skips(self, monkeypatch):
        """已是文档风格不重复改写。"""
        monkeypatch.setattr(
            "src.services.rag.query_rewriter.get_settings",
            lambda: _fake_settings(rewrite_enabled=True, min_chars=20),
        )
        assert should_rewrite("根据项目文档，JWT 配置") is False


class TestLooksAlreadyRewritten:
    """_looks_already_rewritten 检测逻辑。"""

    def test_detects_document_style(self):
        assert _looks_already_rewritten("根据项目文档，系统采用 JWT 认证") is True

    def test_detects_description_style(self):
        assert _looks_already_rewritten("以下是对该功能的详细说明") is True

    def test_short_query_not_detected(self):
        assert _looks_already_rewritten("JWT 配置") is False

    def test_normal_question_not_detected(self):
        assert _looks_already_rewritten("什么是数字孪生") is False


class TestRewriteQuery:
    """rewrite_query 集成测试。"""

    @pytest.mark.asyncio
    async def test_long_query_skips_without_llm(self, monkeypatch):
        """长 query 直接返回原文本，不触发 LLM。"""
        monkeypatch.setattr(
            "src.services.rag.query_rewriter.get_settings",
            lambda: _fake_settings(rewrite_enabled=True, min_chars=20),
        )
        long_query = "这是一个比较长的查询文本应该跳过改写直奔检索"  # >20 chars
        result = await rewrite_query(long_query)
        assert result == long_query

    @pytest.mark.asyncio
    async def test_disabled_returns_original(self, monkeypatch):
        """禁用时返回原 query。"""
        monkeypatch.setattr(
            "src.services.rag.query_rewriter.get_settings",
            lambda: _fake_settings(rewrite_enabled=False, min_chars=20),
        )
        result = await rewrite_query("短")
        assert result == "短"


def _fake_settings(rewrite_enabled: bool, min_chars: int):
    """构造 fake settings 对象。"""

    class FakeSettings:
        kb_query_rewrite_enabled = rewrite_enabled
        kb_query_rewrite_min_chars = min_chars
        kb_query_rewrite_model = ""

    return FakeSettings()
