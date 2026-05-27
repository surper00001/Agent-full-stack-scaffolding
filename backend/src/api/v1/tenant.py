"""租户 API 路由（仅管理员可访问）。"""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, require_admin
from src.db.session import get_db_session
from src.models.schemas.response import APIResponse
from src.models.schemas.tenant import TenantResponse, TokenUsageResponse
from src.services.token_stats_service import TokenStatsService

router = APIRouter(prefix="/tenant", tags=["租户"])


@router.get("", response_model=APIResponse[TenantResponse])
async def get_tenant(
    request: Request,
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """获取当前租户信息（仅管理员）。"""
    tenant_id = getattr(request.state, "tenant_id", "default")
    return APIResponse(
        message="获取成功",
        data=TenantResponse(id=tenant_id),
    )


@router.get("/usage", response_model=APIResponse[TokenUsageResponse])
async def get_token_usage(
    request: Request,
    days: int = Query(default=30, ge=1, le=365, description="统计天数"),
    _admin: CurrentUser = Depends(require_admin),
    db: AsyncSession = Depends(get_db_session),
):
    """获取当前租户的 Token 用量统计（仅管理员）。"""
    service = TokenStatsService(db)
    data = await service.get_tenant_token_usage(days)
    return APIResponse(
        message="获取成功",
        data=TokenUsageResponse(**data),
    )
