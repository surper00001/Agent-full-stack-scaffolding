"""
FastAPI 依赖注入模块。

提供通用的 Depends 函数，如：
- 当前租户 ID 获取
- 当前用户认证
- 分页参数
"""

from fastapi import Header, Request

from src.core.config import get_settings


def get_current_tenant(
    request: Request,
    x_tenant_id: str = Header(default=None, include_in_schema=False),
) -> str:
    """
    获取当前请求的租户 ID。

    优先级：中间件注入 > Header > 默认值
    """
    # 优先从中间件注入的 request.state 获取
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id

    # 其次从 Header 获取
    if x_tenant_id:
        return x_tenant_id

    # 默认
    return get_settings().deafult_tenant_id
