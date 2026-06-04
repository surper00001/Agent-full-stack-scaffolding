"""用户管理 API — 仅管理员可访问。"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_admin
from src.db.session import get_db_session
from src.models.schemas.response import APIResponse, PaginatedData
from src.models.schemas.user_admin import (
    DailyTokenItem,
    SetTokenQuotaRequest,
    UpdateUserRoleRequest,
    UserConversationItem,
    UserDetailResponse,
    UserListItem,
    UserTokenTrendResponse,
    UserTokenUsageItem,
)
from src.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["用户管理"])


@router.get("", response_model=APIResponse[PaginatedData[UserListItem]], summary="用户列表")
async def list_users(
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    search: str | None = Query(default=None, description="搜索关键词（用户名/邮箱/手机号）"),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[UserListItem]]:
    """获取所有用户列表（仅管理员），支持分页和搜索。"""
    service = UserService(db)
    items, total = await service.list_users(
        tenant_id=_admin.tenant_id,
        page=page,
        page_size=page_size,
        search=search,
    )
    pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    return APIResponse(
        message="获取成功",
        data=PaginatedData(
            items=[UserListItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        ),
    )


@router.get("/{user_id}", response_model=APIResponse[UserDetailResponse], summary="用户详情")
async def get_user_detail(
    user_id: str,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[UserDetailResponse]:
    """获取单个用户详细信息（仅管理员）。"""
    service = UserService(db)
    detail = await service.get_user_detail(user_id, tenant_id=_admin.tenant_id)
    return APIResponse(
        message="获取成功",
        data=UserDetailResponse(**detail),
    )


@router.get(
    "/{user_id}/conversations",
    response_model=APIResponse[PaginatedData[UserConversationItem]],
    summary="用户对话列表",
)
async def get_user_conversations(
    user_id: str,
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[PaginatedData[UserConversationItem]]:
    """获取指定用户的所有对话记录（仅管理员）。"""
    service = UserService(db)
    items, total = await service.get_user_conversations(
        user_id=user_id,
        tenant_id=_admin.tenant_id,
        page=page,
        page_size=page_size,
    )
    pages = max(1, (total + page_size - 1) // page_size) if total > 0 else 1
    return APIResponse(
        message="获取成功",
        data=PaginatedData(
            items=[UserConversationItem(**item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
            pages=pages,
        ),
    )


@router.get(
    "/{user_id}/token-usage",
    response_model=APIResponse[UserTokenTrendResponse],
    summary="用户 Token 消耗明细",
)
async def get_user_token_usage(
    user_id: str,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[UserTokenTrendResponse]:
    """获取指定用户的 Token 消耗明细（按对话聚合）（仅管理员）。"""
    service = UserService(db)
    data = await service.get_user_token_usage(user_id, tenant_id=_admin.tenant_id)
    return APIResponse(
        message="获取成功",
        data=UserTokenTrendResponse(**data),
    )


@router.get(
    "/{user_id}/token-trend",
    response_model=APIResponse[list[DailyTokenItem]],
    summary="用户 Token 使用趋势",
)
async def get_user_token_trend(
    user_id: str,
    days: int = Query(default=7, ge=1, le=365, description="统计天数"),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[list[DailyTokenItem]]:
    """获取指定用户的 Token 按日使用趋势（仅管理员）。"""
    service = UserService(db)
    trend = await service.get_user_token_trend(user_id, tenant_id=_admin.tenant_id, days=days)
    return APIResponse(
        message="获取成功",
        data=[DailyTokenItem(**item) for item in trend],
    )


@router.delete("/{user_id}", response_model=APIResponse, summary="删除用户")
async def delete_user(
    user_id: str,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """软删除指定用户（仅管理员）。管理员账户不可删除自身。"""
    service = UserService(db)
    await service.delete_user(user_id, tenant_id=_admin.tenant_id)
    return APIResponse(message="用户已删除")


@router.delete("/{user_id}/conversations", response_model=APIResponse, summary="清空用户对话")
async def delete_user_conversations(
    user_id: str,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """清空指定用户的所有对话记录（仅管理员）。"""
    service = UserService(db)
    count = await service.delete_user_conversations(user_id, tenant_id=_admin.tenant_id)
    return APIResponse(message=f"已清空 {count} 条对话记录")


@router.put("/{user_id}/token-quota", response_model=APIResponse, summary="设置 Token 配额")
async def set_token_quota(
    user_id: str,
    body: SetTokenQuotaRequest,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """设置指定用户的 Token 配额上限（仅管理员）。"""
    service = UserService(db)
    result = await service.set_token_quota(user_id, tenant_id=_admin.tenant_id, token_quota=body.token_quota)
    return APIResponse(
        message="Token 配额已更新",
        data=result,
    )


@router.put("/{user_id}/role", response_model=APIResponse, summary="更新用户角色")
async def update_user_role(
    user_id: str,
    body: UpdateUserRoleRequest,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """更新指定用户的角色（仅管理员）。"""
    service = UserService(db)
    result = await service.update_user_role(user_id, tenant_id=_admin.tenant_id, role=body.role)
    return APIResponse(
        message="用户角色已更新",
        data=result,
    )


@router.post("/{user_id}/toggle-active", response_model=APIResponse, summary="启用/禁用用户")
async def toggle_user_active(
    user_id: str,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse:
    """启用或禁用指定用户（仅管理员）。"""
    service = UserService(db)
    result = await service.toggle_user_active(user_id, tenant_id=_admin.tenant_id)
    return APIResponse(
        message=f"用户已{'启用' if result['is_active'] else '禁用'}",
        data=result,
    )
