"""
API 限流中间件。

基于 Redis 滑动窗口算法，为敏感端点提供频率限制保护。
- 全局默认：120 次/分钟
- 登录/注册端点：5 次/分钟
- 管理员端点：30 次/分钟

当 Redis 不可用时自动降级为允许所有请求（fail-open）。

配置常量：
    RATE_LIMIT_ENABLED: 是否启用限流（默认 True）
    RATE_LIMIT_REDIS_URL: 覆盖默认 Redis 连接
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse as FastAPIJSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:

    from fastapi import Request
    from starlette.responses import Response as StarletteResponse

from src.core.config import get_settings

# ── 端点速率配置 ──
_LIMITS: dict[str, tuple[int, int]] = {
    # 路径前缀 → (最大请求数, 窗口秒数)
    "/api/v1/auth/login": (5, 60),
    "/api/v1/auth/register": (5, 60),
    "/api/v1/auth/send-code": (3, 60),
    "/api/v1/auth/captcha": (5, 60),      # 防止验证码滥用
    "/api/v1/auth/refresh": (20, 60),
    "/api/v1/admin": (30, 60),
}
_GLOBAL_RATE = (120, 60)  # 全局默认


def _match_limit(path: str) -> tuple[int, int]:
    """匹配路径对应的速率限制。"""
    for prefix, limit in _LIMITS.items():
        if path.startswith(prefix):
            return limit
    return _GLOBAL_RATE


class RateLimitMiddleware(BaseHTTPMiddleware):
    """基于 Redis 滑动窗口的 API 限流中间件。"""

    async def dispatch(  # noqa: A003
        self, request: Request, call_next: RequestResponseEndpoint,
    ) -> StarletteResponse:
        settings = get_settings()

        # 可配置关闭限流
        if not getattr(settings, "rate_limit_enabled", True):
            return await call_next(request)

        try:
            from src.core.redis import get_redis_client
        except ImportError:
            return await call_next(request)

        redis = await get_redis_client()
        if redis is None:
            # Redis 不可用，fail-open 放行
            return await call_next(request)

        # 构建限流 key：rate:<path>:<client_ip>
        client_ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.client.host if request.client
            else "unknown"
        )
        max_req, window_sec = _match_limit(request.url.path)
        rate_key = f"rate_limit:{request.url.path}:{client_ip}"

        now = time.time()
        window_start = now - window_sec

        try:
            # 滑动窗口：删除过期记录 + 计数 + 添加当前请求
            async with redis.pipeline() as pipe:
                pipe.zremrangebyscore(rate_key, 0, window_start)
                pipe.zcard(rate_key)
                pipe.zadd(rate_key, {str(now): now})
                pipe.expire(rate_key, window_sec * 2)
                _, count, _, _ = await pipe.execute()
        except Exception as e:
            # Redis 操作异常，fail-open（避免因 Redis 故障阻塞所有流量）
            logger.warning(f"限流 Redis 操作失败，fail-open: {e}")
            return await call_next(request)

        if count >= max_req:
            retry_after = window_sec
            return FastAPIJSONResponse(
                status_code=429,
                content={
                    "success": False,
                    "code": 42900,
                    "message": f"请求过于频繁，请 {retry_after} 秒后重试",
                    "detail": {
                        "retry_after": retry_after,
                        "limit": max_req,
                        "window": window_sec,
                    },
                },
                headers={
                    "Retry-After": str(retry_after),
                    "X-RateLimit-Limit": str(max_req),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now) + window_sec),
                },
            )

        # 正常放行，注入限流状态头
        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(max_req)
        response.headers["X-RateLimit-Remaining"] = str(
            max(0, max_req - count - 1)
        )
        response.headers["X-RateLimit-Reset"] = str(
            int(now) + window_sec
        )
        return response
