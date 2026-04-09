"""
请求日志中间件。

记录每个 HTTP 请求的：
- 请求方法、路径、状态码
- 处理耗时
- 租户 ID
- 请求 ID（追踪用）
"""

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from loguru import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """HTTP 请求日志中间件。"""

    async def dispatch(self, request: Request, call_next) -> Response:
        # 生成请求 ID
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id

        start = time.monotonic()

        # 执行请求
        response = await call_next(request)

        # 计算耗时
        elapsed_ms = (time.monotonic() - start) * 1000
        tenant_id = getattr(request.state, "tenant_id", "-")

        # 结构化日志
        logger.info(
            f"[{request_id}] {request.method} {request.url.path} "
            f"-> {response.status_code} | {elapsed_ms:.1f}ms | tenant={tenant_id}"
        )

        # 注入响应头
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"

        return response
