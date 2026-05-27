"""
数据库会话管理模块。

提供异步 SQLAlchemy 引擎与会话工厂，
支持 PostgreSQL（生产）/ SQLite（开发测试）。
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.core.config import get_settings


def _build_async_url() -> str:
    """根据配置构建异步数据库 URL。

    优先级：PYTEST 环境 → SQLite 内存，配置了 PG 密码 → PG，否则 → 本地 SQLite。
    """
    import os
    from pathlib import Path

    # 测试环境：强制使用 SQLite 内存数据库
    if os.environ.get("PYTEST_RUNNING") == "1":
        return "sqlite+aiosqlite:///:memory:"

    settings = get_settings()
    password = settings.db_password.get_secret_value()

    # 如果配置了 PostgreSQL 密码（非空），优先使用 PG
    if password:
        return settings.database_url  # PostgreSQL

    # 回退到 SQLite（开发 / 无 PG 环境）
    db_path = Path("./data/app.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{db_path.resolve()}"


def _build_engine_kwargs() -> dict:
    """根据数据库类型构建引擎参数。"""
    settings = get_settings()
    url = _build_async_url()

    kwargs: dict = {"echo": settings.db_echo}

    if url.startswith("postgresql"):
        # PostgreSQL 使用 asyncpg 的 pool
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow
        kwargs["pool_pre_ping"] = True
    # SQLite 不设置 pool 参数（使用默认 NullPool）

    return kwargs


# 全局异步引擎（应用启动时创建）
_engine = create_async_engine(
    _build_async_url(),
    **_build_engine_kwargs(),
)

# 异步会话工厂
AsyncSessionLocal = async_sessionmaker(
    bind=_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖注入：获取数据库会话。

    使用示例:
        @router.get("/items")
        async def list_items(db: AsyncSession = Depends(get_db_session)):
            ...
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def close_db_engine() -> None:
    """关闭数据库引擎（应用关闭时调用）。

    优雅处理事件循环已关闭的情况，避免 shutdown 时产生噪音日志。
    """
    import asyncio

    try:
        await asyncio.wait_for(_engine.dispose(), timeout=5)
    except (asyncio.TimeoutError, RuntimeError, ConnectionResetError):
        pass  # 事件循环正在关闭或连接已不可达，忽略
