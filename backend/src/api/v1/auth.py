"""认证 API 路由。"""

import pyotp
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import CurrentUser, get_current_tenant, get_current_user
from src.core.config import get_settings
from src.core.redis import get_redis
from src.db.session import get_db_session
from src.models.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    SendCodeRequest,
    TokenResponse,
    UpdateProfileRequest,
    UserResponse,
)
from src.models.schemas.response import APIResponse
from src.services.auth_service import AuthService
from src.utils.captcha import generate_captcha

router = APIRouter(prefix="/auth", tags=["认证"])


@router.get("/captcha")
async def get_captcha(
    target: str = Query(description="手机号或邮箱"),
):
    """获取图形验证码图片。验证码存入 Redis，返回 PNG 图片。"""
    settings = get_settings()

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret, digits=6, interval=settings.verification_code_ttl)
    code = totp.now().zfill(6)

    redis = await get_redis()
    key = f"captcha:{target}"
    await redis.setex(key, settings.verification_code_ttl, secret)

    img_bytes = generate_captcha(code)
    return Response(content=img_bytes, media_type="image/png")


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
    """用户登录：先验图形验证码 → 返回 Access Token + Refresh Token。"""
    service = AuthService(db)
    token_data = await service.login(body.account, body.password, body.code)
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


@router.put("/profile", response_model=APIResponse[UserResponse], summary="更新个人信息")
async def update_profile(
    body: UpdateProfileRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[UserResponse]:
    """更新当前用户的个人信息（用户名/邮箱/手机号）。"""
    service = AuthService(db)
    user = await service.update_profile(
        user_id=current_user.id,
        username=body.username,
        email=body.email,
        phone=body.phone,
    )
    return APIResponse(message="个人信息已更新", data=UserResponse.model_validate(user))


@router.put("/password", response_model=APIResponse[None], summary="修改密码")
async def change_password(
    body: ChangePasswordRequest,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> APIResponse[None]:
    """修改当前用户的登录密码。"""
    service = AuthService(db)
    await service.change_password(
        user_id=current_user.id,
        old_password=body.old_password,
        new_password=body.new_password,
    )
    return APIResponse(message="密码已修改")
