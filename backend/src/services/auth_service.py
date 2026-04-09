"""认证服务层：注册、登录、验证码、双 Token 管理。"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import pyotp

from src.core.config import get_settings
from src.core.exceptions import (
    InvalidCredentialsError,
    InvalidVerificationCodeError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from src.core.redis import get_redis
from src.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    verify_password,
)
from src.db.repository import BaseRepository
from src.models.domain.refresh_token import RefreshToken
from src.models.domain.user import User


class AuthService:
    """认证业务服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._user_repo = BaseRepository[User](User, session)
        self._token_repo = BaseRepository[RefreshToken](RefreshToken, session)
        self._session = session

    # ---- 验证码 ----

    async def send_verification_code(self, target: str, method: str = "email") -> str:
        """发送验证码，返回生成的验证码（开发环境可返回，生产环境通过 SMS/邮件发送）。"""
        settings = get_settings()

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret, interval=settings.verification_code_ttl)
        code = totp.now()

        redis = await get_redis()
        key = f"verify_code:{method}:{target}"
        await redis.setex(key, settings.verification_code_ttl, secret)

        return code

    async def _verify_code(self, target: str, method: str, code: str) -> bool:
        """验证验证码是否有效。"""
        settings = get_settings()
        redis = await get_redis()
        key = f"verify_code:{method}:{target}"
        secret = await redis.get(key)

        if secret is None:
            return False

        totp = pyotp.TOTP(secret, interval=settings.verification_code_ttl)
        if not totp.verify(code):
            return False

        await redis.delete(key)
        return True

    # ---- 注册 ----

    async def register(
        self,
        username: str,
        password: str,
        code: str,
        phone: str | None = None,
        email: str | None = None,
        tenant_id: str = "default",
    ) -> User:
        """用户注册：先验码，再检查唯一性，最后创建用户。"""
        verify_target = email or phone or ""
        verify_method = "email" if email else "sms"
        if not await self._verify_code(verify_target, verify_method, code):
            raise InvalidVerificationCodeError()

        await self._check_unique(username, phone, email)

        user = User(
            username=username,
            phone=phone,
            email=email,
            hashed_password=hash_password(password),
            is_verified=True,
            tenant_id=tenant_id,
        )
        return await self._user_repo.create(user)

    async def _check_unique(
        self, username: str, phone: str | None, email: str | None
    ) -> None:
        """检查用户名、手机号、邮箱是否已被注册。"""
        if await self._get_by_username(username):
            raise UserAlreadyExistsError("用户名", username)
        if phone and await self._get_by_phone(phone):
            raise UserAlreadyExistsError("手机号", phone)
        if email and await self._get_by_email(email):
            raise UserAlreadyExistsError("邮箱", email)

    # ---- 登录（双 Token） ----

    async def login(self, account: str, password: str) -> dict:
        """用户登录：验证凭证 → 签发 Access Token + Refresh Token。"""
        user = await self._find_by_account(account)
        if user is None or not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()
        if not user.is_active:
            raise InvalidCredentialsError()

        return await self._issue_tokens(user)

    async def _issue_tokens(self, user: User) -> dict:
        """签发双 Token：Access Token（短效 JWT）+ Refresh Token（长效随机串）。"""
        settings = get_settings()

        # Access Token（JWT，短有效期）
        access_token, expires_in = create_access_token(
            data={"sub": user.id, "username": user.username},
        )

        # Refresh Token（随机字符串，长有效期）
        raw_refresh, token_hash = generate_refresh_token()
        refresh_token_record = RefreshToken(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=datetime.now(timezone.utc)
            + timedelta(days=settings.jwt_refresh_token_expire_days),
        )
        await self._token_repo.create(refresh_token_record)

        return {
            "access_token": access_token,
            "refresh_token": raw_refresh,
            "token_type": "bearer",
            "expires_in": expires_in,
        }

    # ---- 刷新 ----

    async def refresh_access_token(self, raw_refresh_token: str) -> dict:
        """使用 Refresh Token 刷新 Access Token（轮换制：旧 Token 失效，发新 Token）。"""
        token_hash = hash_password(raw_refresh_token)

        # 查找匹配的 RefreshToken
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        token_record = result.scalar_one_or_none()

        if token_record is None or token_record.is_expired:
            raise InvalidCredentialsError()

        # 撤销旧 Refresh Token（防止重放攻击）
        token_record.is_revoked = True
        await self._session.flush()

        # 获取用户
        user = await self._user_repo.get_by_id(token_record.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError()

        # 签发新双 Token
        return await self._issue_tokens(user)

    # ---- 登出 ----

    async def logout(self, raw_refresh_token: str) -> None:
        """登出：撤销 Refresh Token。"""
        token_hash = hash_password(raw_refresh_token)

        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        token_record = result.scalar_one_or_none()

        if token_record is not None:
            token_record.is_revoked = True
            await self._session.flush()

    # ---- 当前用户 ----

    async def get_current_user(self, token: str) -> User | None:
        """从 JWT Access Token 获取当前用户。"""
        payload = decode_access_token(token)
        if payload is None:
            return None
        user_id = payload.get("sub")
        if user_id is None:
            return None
        return await self._user_repo.get_by_id(user_id)

    # ---- 查询辅助 ----

    async def _get_by_username(self, username: str) -> User | None:
        users = await self._user_repo.list_all(username=username)
        return users[0] if users else None

    async def _get_by_phone(self, phone: str) -> User | None:
        users = await self._user_repo.list_all(phone=phone)
        return users[0] if users else None

    async def _get_by_email(self, email: str) -> User | None:
        users = await self._user_repo.list_all(email=email)
        return users[0] if users else None

    async def _find_by_account(self, account: str) -> User | None:
        stmt = select(User).where(
            or_(
                User.username == account,
                User.phone == account,
                User.email == account,
            ),
            User.is_deleted == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
