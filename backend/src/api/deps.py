"""
FastAPI 依赖注入模块。

提供通用的 Depends 函数，如：
- 当前租户 ID 获取
- 当前用户认证
- 管理员权限检查
- 分页参数
"""

from typing import NamedTuple

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.exceptions import ForbiddenError, UnauthorizedError
from src.core.security import decode_access_token
from src.db.repository import BaseRepository
from src.db.session import get_db_session
from src.models.domain.user import User


class CurrentUser(NamedTuple):
    """从 JWT 解析出的当前用户信息。"""
    id: str
    username: str
    role: str
    tenant_id: str


def get_current_tenant(
    request: Request,
    x_tenant_id: str = Header(default=None, include_in_schema=False),
) -> str:
    """
    获取当前请求的租户 ID。

    优先级：中间件注入 > Header > 默认值
    """
    # 优先从中间件注入的 request.state 获取
    tenant_id: str | None = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id

    # 其次从 Header 获取
    if x_tenant_id:
        return x_tenant_id

    # 默认
    return get_settings().default_tenant_id


async def get_current_user(
    authorization: str = Header(description="Bearer <access_token>"),
    db: AsyncSession = Depends(get_db_session),
) -> CurrentUser:
    """从 Authorization Header 解析 JWT 并返回当前用户信息（Depends 注入）。"""
    if not authorization.startswith("Bearer "):
        raise UnauthorizedError("未提供认证令牌")

    token = authorization.removeprefix("Bearer ")
    payload = decode_access_token(token)
    if payload is None:
        raise UnauthorizedError("令牌无效或已过期")

    user_id = payload.get("sub")
    username = payload.get("username", "")
    role = payload.get("role", "user")
    tenant_id = payload.get("tenant_id", "default")

    if user_id is None:
        raise UnauthorizedError("令牌无效")

    # 验证用户仍然存在且启用
    repo = BaseRepository[User](User, db)
    user = await repo.get_by_id(user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已禁用")

    return CurrentUser(id=user_id, username=username, role=role, tenant_id=tenant_id)


async def require_admin(
    current_user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """要求当前用户为管理员，否则抛出 403。"""
    if current_user.role != "admin":
        raise ForbiddenError("需要管理员权限")
    return current_user
