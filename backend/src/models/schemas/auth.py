"""认证相关 Pydantic Schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


# ---- 请求 ----
class SendCodeRequest(BaseModel):
    """发送验证码请求。"""

    target: str = Field(description="手机号或邮箱地址")
    method: str = Field(default="email", description="发送方式: sms | email")


class RegisterRequest(BaseModel):
    """用户注册请求。"""

    username: str = Field(min_length=2, max_length=50, description="用户名")
    phone: str | None = Field(default=None, pattern=r"^1[3-9]\d{9}$", description="手机号")
    email: str | None = Field(default=None, description="邮箱")
    password: str = Field(min_length=6, max_length=128, description="密码")
    code: str = Field(min_length=6, max_length=6, description="6位验证码")


class LoginRequest(BaseModel):
    """用户登录请求。"""

    account: str = Field(description="用户名 / 手机号 / 邮箱")
    password: str = Field(description="密码")


class RefreshRequest(BaseModel):
    """刷新令牌请求。"""

    refresh_token: str = Field(description="Refresh Token")


# ---- 响应 ----
class TokenResponse(BaseModel):
    """双 Token 响应。"""

    access_token: str = Field(description="JWT 访问令牌（短有效期）")
    refresh_token: str = Field(description="Refresh Token（长有效期）")
    token_type: str = Field(default="bearer", description="令牌类型")
    expires_in: int = Field(description="Access Token 过期时间（秒）")


class UserResponse(BaseModel):
    """用户信息响应。"""

    id: str
    username: str
    phone: str | None
    email: str | None
    is_active: bool
    is_verified: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
