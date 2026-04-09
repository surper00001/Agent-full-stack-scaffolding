"""认证 API 路由。"""

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_tenant
from src.db.session import get_db_session
from src.models.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SendCodeRequest,
    TokenResponse,
    UserResponse,
)
from src.models.schemas.response import APIResponse
from src.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/send-code", response_model=APIResponse[dict])
async def send_verification_code(
    body: SendCodeRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """发送验证码到手机或邮箱。"""
    service = AuthService(db)
    code = await service.send_verification_code(body.target, body.method)
    return APIResponse(
        message="验证码已发送",
        data={"target": body.target, "code": code},
    )


@router.post("/register", response_model=APIResponse[UserResponse], status_code=201)
async def register(
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db_session),
    tenant_id: str = Depends(get_current_tenant),
):
    """用户注册。"""
    service = AuthService(db)
    user = await service.register(
        username=body.username,
        password=body.password,
        code=body.code,
        phone=body.phone,
        email=body.email,
        tenant_id=tenant_id,
    )
    return APIResponse(
        message="注册成功",
        data=UserResponse.model_validate(user),
    )


@router.post("/login", response_model=APIResponse[TokenResponse])
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """用户登录：返回 Access Token + Refresh Token。"""
    service = AuthService(db)
    token_data = await service.login(body.account, body.password)
    return APIResponse(
        message="登录成功",
        data=TokenResponse(**token_data),
    )


@router.post("/refresh", response_model=APIResponse[TokenResponse])
async def refresh_token(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """刷新令牌：使用 Refresh Token 获取新的双 Token 对。"""
    service = AuthService(db)
    token_data = await service.refresh_access_token(body.refresh_token)
    return APIResponse(
        message="令牌刷新成功",
        data=TokenResponse(**token_data),
    )


@router.post("/logout", response_model=APIResponse[None])
async def logout(
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db_session),
):
    """用户登出：撤销 Refresh Token。"""
    service = AuthService(db)
    await service.logout(body.refresh_token)
    return APIResponse(message="已登出")


@router.get("/me", response_model=APIResponse[UserResponse])
async def get_current_user(
    authorization: str = Header(description="Bearer <access_token>"),
    db: AsyncSession = Depends(get_db_session),
):
    """获取当前登录用户信息。"""
    if not authorization.startswith("Bearer "):
        return APIResponse(code=40100, message="未认证", data=None)

    token = authorization.removeprefix("Bearer ")
    service = AuthService(db)
    user = await service.get_current_user(token)

    if user is None:
        return APIResponse(code=40101, message="令牌无效或已过期", data=None)

    return APIResponse(
        message="已认证",
        data=UserResponse.model_validate(user),
    )
