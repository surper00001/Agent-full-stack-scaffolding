"""认证服务层：注册、登录、验证码、双 Token 管理。"""

from datetime import UTC, datetime, timedelta

import pyotp
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    hash_refresh_token,
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

    async def send_verification_code(self, target: str, method: str = "email") -> str:  # noqa: ARG002
        """发送验证码，返回生成的验证码（开发环境可返回，生产环境通过 SMS/邮件发送）。"""
        settings = get_settings()

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret, digits=6, interval=settings.verification_code_ttl)
        code = totp.now().zfill(6)

        redis = await get_redis()
        key = f"verify_code:{target}"
        await redis.setex(key, settings.verification_code_ttl, secret)

        return code

    async def _verify_code(self, target: str, method: str, code: str) -> bool:  # noqa: ARG002
        """验证验证码是否有效 — 优先匹配 captcha，其次 send-code。"""
        settings = get_settings()
        redis = await get_redis()

        # 尝试两种 key：captcha（图片验证码）和 verify_code（邮箱/短信）
        for prefix in ("captcha", "verify_code"):
            key = f"{prefix}:{target}"
            secret = await redis.get(key)
            if secret is None:
                continue

            totp = pyotp.TOTP(secret, digits=6, interval=settings.verification_code_ttl)
            if totp.verify(code):
                await redis.delete(key)
                return True

        return False

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
        # 与前端 captcha ?target= 保持一致（邮箱优先，其次手机）
        verify_target = email or phone or ""
        if not await self._verify_code(verify_target, "captcha", code):
            raise InvalidVerificationCodeError()

        await self._check_unique(username, phone, email, tenant_id)

        user = User(
            username=username,
            phone=phone,
            email=email,
            hashed_password=hash_password(password),
            is_verified=True,
            tenant_id=tenant_id,
        )
        result = await self._user_repo.create(user)
        logger.info(f"用户注册: user_id={result.id}, username={username}, tenant={tenant_id}")
        return result

    async def _check_unique(
        self, username: str, phone: str | None, email: str | None, tenant_id: str,
    ) -> None:
        """检查用户名、手机号、邮箱是否已被注册（租户范围内唯一）。
        使用通用错误消息防止用户枚举攻击。
        """
        if await self._get_by_username(username, tenant_id):
            raise UserAlreadyExistsError("该账号信息已被注册", value="")
        if phone and await self._get_by_phone(phone, tenant_id):
            raise UserAlreadyExistsError("该账号信息已被注册", value="")
        if email and await self._get_by_email(email, tenant_id):
            raise UserAlreadyExistsError("该账号信息已被注册", value="")

    # ---- 登录（双 Token） ----

    async def login(self, account: str, password: str, code: str | None = None) -> dict:
        """用户登录：先验图形验证码 → 再验凭证 → 签发双 Token。"""
        if code:  # noqa: SIM102
            if not await self._verify_code(account, "captcha", code):
                logger.warning(f"登录失败（验证码错误）: account={account}")
                raise InvalidVerificationCodeError()

        user = await self._find_by_account(account)
        if user is None or not verify_password(password, user.hashed_password):
            logger.warning(f"登录失败（凭证错误）: account={account}")
            raise InvalidCredentialsError()
        if not user.is_active:
            logger.warning(f"登录失败（账户禁用）: account={account}, user_id={user.id}")
            raise InvalidCredentialsError()

        logger.info(f"登录成功: user_id={user.id}, username={user.username}")
        return await self._issue_tokens(user)

    async def _issue_tokens(self, user: User) -> dict:
        """签发双 Token：Access Token（短效 JWT）+ Refresh Token（长效随机串）。"""
        settings = get_settings()

        # Access Token（JWT，短有效期）
        access_token, expires_in = create_access_token(
            data={
                "sub": user.id,
                "username": user.username,
                "role": user.role,
                "tenant_id": user.tenant_id,
            },
        )

        # Refresh Token（随机字符串，长有效期）
        raw_refresh, token_hash = generate_refresh_token()
        refresh_token_record = RefreshToken(
            token_hash=token_hash,
            user_id=user.id,
            expires_at=datetime.now(UTC)
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
        token_hash = hash_refresh_token(raw_refresh_token)

        # 查找匹配的 RefreshToken
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == token_hash,
            RefreshToken.is_revoked == False,  # noqa: E712
        )
        result = await self._session.execute(stmt)
        token_record = result.scalar_one_or_none()

        if token_record is None or token_record.is_expired:
            logger.warning("Token 刷新失败（无效或已过期）")
            raise InvalidCredentialsError()

        # 撤销旧 Refresh Token（防止重放攻击）
        token_record.is_revoked = True
        await self._session.flush()
        logger.info(f"Token 刷新成功: user_id={token_record.user_id}")

        # 获取用户
        user = await self._user_repo.get_by_id(token_record.user_id)
        if user is None or not user.is_active:
            raise InvalidCredentialsError()

        # 签发新双 Token
        return await self._issue_tokens(user)

    # ---- 登出 ----

    async def logout(self, raw_refresh_token: str) -> None:
        """登出：撤销 Refresh Token。"""
        token_hash = hash_refresh_token(raw_refresh_token)

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
        """从 JWT Access Token 获取当前用户（租户范围内）。"""
        payload = decode_access_token(token)
        if payload is None:
            return None
        user_id = payload.get("sub")
        tenant_id = payload.get("tenant_id", "default")
        if user_id is None:
            return None
        return await self._user_repo.get_by_id_with_tenant(user_id, tenant_id)

    # ---- 查询辅助 ----

    async def _get_by_username(self, username: str, tenant_id: str) -> User | None:
        users = await self._user_repo.list_all(tenant_id=tenant_id, username=username)
        return users[0] if users else None

    async def _get_by_phone(self, phone: str, tenant_id: str) -> User | None:
        users = await self._user_repo.list_all(tenant_id=tenant_id, phone=phone)
        return users[0] if users else None

    async def _get_by_email(self, email: str, tenant_id: str) -> User | None:
        users = await self._user_repo.list_all(tenant_id=tenant_id, email=email)
        return users[0] if users else None

    # ---- 个人信息管理 ----

    async def update_profile(
        self,
        user_id: str,
        tenant_id: str,
        username: str | None = None,
        email: str | None = None,
        phone: str | None = None,
    ) -> User:
        """更新用户个人信息。"""
        user = await self._user_repo.get_by_id_with_tenant(user_id, tenant_id)
        if user is None:
            raise UserNotFoundError()

        if username is not None:
            existing = await self._get_by_username(username, tenant_id)
            if existing and existing.id != user_id:
                raise UserAlreadyExistsError("用户名", username)
            user.username = username

        if email is not None:
            existing = await self._get_by_email(email, tenant_id)
            if existing and existing.id != user_id:
                raise UserAlreadyExistsError("邮箱", email)
            user.email = email

        if phone is not None:
            existing = await self._get_by_phone(phone, tenant_id)
            if existing and existing.id != user_id:
                raise UserAlreadyExistsError("手机号", phone)
            user.phone = phone

        return await self._user_repo.update(user)

    async def change_password(
        self,
        user_id: str,
        tenant_id: str,
        old_password: str,
        new_password: str,
    ) -> None:
        """修改用户密码。"""
        user = await self._user_repo.get_by_id_with_tenant(user_id, tenant_id)
        if user is None:
            raise UserNotFoundError()

        if not verify_password(old_password, user.hashed_password):
            raise InvalidCredentialsError()

        user.hashed_password = hash_password(new_password)
        await self._user_repo.update(user)

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
