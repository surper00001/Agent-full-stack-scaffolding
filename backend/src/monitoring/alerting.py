"""
轻量告警管理器。

提供关键事件的 Webhook 通知机制，支持：
- 断路器熔断告警
- 连续认证失败告警
- KB 处理失败告警
- LLM 重试耗尽告警

配置方式（.env）：
    ALERT_WEBHOOK_URL=https://hooks.slack.com/...   # Slack/Discord/自定义 Webhook
    ALERT_ENABLED=true                                # 是否启用告警
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger


@dataclass
class Alert:
    """告警事件。"""
    level: str  # critical / warning / info
    category: str  # auth / llm / kb / circuit / rate_limit
    title: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


class AlertManager:
    """
    告警管理器 — 聚合关键事件并通过 Webhook 发送。

    使用方式:
        alerts = AlertManager(webhook_url="https://hooks.slack.com/...")
        await alerts.send(Alert(level="critical", category="llm", ...))

        # 或内联发送
        await alerts.critical("llm", "LLM 不可用", "DeepSeek API 返回 503")
    """

    def __init__(self, webhook_url: str = "", enabled: bool = True) -> None:
        self._webhook_url = webhook_url
        self._enabled = enabled
        self._client: httpx.AsyncClient | None = None

        # 聚合计数器（防止告警风暴）
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._cooldown: dict[str, float] = {}  # category -> next_allowed_time

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def send(self, alert: Alert, cooldown_seconds: int = 300) -> bool:
        """
        发送告警。

        Args:
            alert: 告警事件
            cooldown_seconds: 同类告警冷却时间（秒），防止风暴
        """
        if not self._enabled or not self._webhook_url:
            return False

        import time as _time
        now = _time.time()

        # 冷却检查
        with self._lock:
            last = self._cooldown.get(alert.category, 0)
            if now < last:
                return False
            self._cooldown[alert.category] = now + cooldown_seconds
            self._counters[alert.category] += 1

        # 构建载荷
        count = self._counters[alert.category]
        payload = {
            "level": alert.level,
            "category": alert.category,
            "title": alert.title,
            "message": alert.message,
            "details": alert.details,
            "tags": alert.tags,
            "count": count,
            "timestamp": _time.time(),
        }

        try:
            client = await self._ensure_client()
            resp = await client.post(
                self._webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning(f"告警 Webhook 失败 HTTP {resp.status_code}: {resp.text[:200]}")
                return False
            logger.info(f"告警已发送: [{alert.category}] {alert.title} (#{count})")
            return True
        except Exception as e:
            logger.debug(f"告警发送异常: {e}")
            return False

    # ── 快捷方法 ──

    async def critical(self, category: str, title: str, message: str, **details: Any) -> bool:
        return await self.send(Alert(level="critical", category=category, title=title, message=message, details=details))

    async def warning(self, category: str, title: str, message: str, **details: Any) -> bool:
        return await self.send(Alert(level="warning", category=category, title=title, message=message, details=details))

    async def info(self, category: str, title: str, message: str, **details: Any) -> bool:
        return await self.send(Alert(level="info", category=category, title=title, message=message, details=details))

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None


# ── 全局单例 ──

_alert_manager: AlertManager | None = None


def get_alert_manager() -> AlertManager:
    """获取全局告警管理器。从配置读取 Webhook URL。"""
    global _alert_manager
    if _alert_manager is None:
        from src.core.config import get_settings
        settings = get_settings()
        webhook_url = getattr(settings, "alert_webhook_url", "")
        enabled = getattr(settings, "alert_enabled", webhook_url != "")
        _alert_manager = AlertManager(webhook_url=webhook_url, enabled=enabled)
    return _alert_manager
