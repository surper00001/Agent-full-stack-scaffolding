"""
安全头中间件。

为所有 HTTP 响应添加安全相关的 HTTP 头部：
- Content-Security-Policy (CSP)
- Strict-Transport-Security (HSTS)
- X-Frame-Options
- X-Content-Type-Options
- Referrer-Policy
- Permissions-Policy

详细参考：OWASP Secure Headers Project
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """为所有响应添加安全头。"""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        headers = response.headers

        # ── 防止 MIME 类型嗅探 ──
        headers.setdefault("X-Content-Type-Options", "nosniff")

        # ── 防止点击劫持 ──
        headers.setdefault("X-Frame-Options", "DENY")

        # ── 引荐来源策略 ──
        headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )

        # ── 权限策略（限制浏览器特性 API） ──
        headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), "
            "interest-cohort=()",
        )

        # ── HSTS（仅 HTTPS 环境生效） ──
        # 开发环境 HTTP 下不设置，避免浏览器拒绝访问
        if request.url.scheme == "https":
            headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains; preload",
            )

        # ── CSP（内容安全策略） ──
        # 使用较宽松但仍具防护力的策略，适应 SPA + API 场景
        csp_parts = [
            "default-src 'self'",
            "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob: https:",
            "font-src 'self' data:",
            "connect-src 'self' https: wss:",
            # Media (音频/视频)
            "media-src 'self' blob: data:",
            # 对象嵌入
            "object-src 'none'",
            # 表单提交目标
            "form-action 'self'",
            # 基础 URI
            "base-uri 'self'",
        ]
        headers.setdefault(
            "Content-Security-Policy", "; ".join(csp_parts)
        )

        return response
