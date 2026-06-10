"""
多租户中间件。

从请求头中提取租户 ID，注入到请求上下文中，
实现透明的租户隔离。
"""


from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from src.core.config import get_settings


class TenantMiddleware(BaseHTTPMiddleware):
    """
    租户识别中间件。

    从 HTTP 头 x-tenant-id 中提取租户标识，
    存储到 request.state.tenant_id 供下游使用。
    未启用多租户时，使用默认租户 ID。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        settings = get_settings()

        if settings.multi_tenant_enabled:
            tenant_id = request.headers.get(
                settings.tenant_header_name, settings.default_tenant_id
            )
        else:
            tenant_id = settings.default_tenant_id

        # 注入到请求状态
        request.state.tenant_id = tenant_id

        # 继续处理
        response = await call_next(request)
        return response


def get_tenant_id(request: Request) -> str:
    """从请求中获取当前租户 ID（供 FastAPI Depends 使用）。"""
    return getattr(request.state, "tenant_id", "default")
