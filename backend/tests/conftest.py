"""
测试全局配置。

提供 pytest fixtures：
- 异步 HTTP 测试客户端（SQLite 内存数据库）
- 数据库会话（SQLite 内存数据库）
- Mock LLM 工厂

测试环境通过 PYTEST_RUNNING=1 环境变量强制使用 SQLite 内存数据库。
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.base import Base

# 在模块加载时设置测试环境标志，session 模块会据此选择 SQLite 内存数据库
os.environ["PYTEST_RUNNING"] = "1"


@pytest.fixture(scope="session")
def event_loop():
    """创建 session 级别的事件循环。"""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """
    创建异步 HTTP 测试客户端。

    自动使用 SQLite 内存数据库（PYTEST_RUNNING=1），
    不影响本地 PostgreSQL 数据。
    通过 dependency_overrides 绕过认证。
    """
    from unittest.mock import AsyncMock

    from src.main import create_app

    app = create_app()

    # 确保测试表已创建
    from src.db.session import _engine

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 覆盖认证依赖，让测试无需真实 token
    from src.api import deps as api_deps

    mock_user = api_deps.CurrentUser(
        id="00000000-0000-0000-0000-000000000001",
        username="test_user",
        role="admin",
    )
    app.dependency_overrides[api_deps.get_current_user] = lambda: mock_user
    app.dependency_overrides[api_deps.require_admin] = lambda: mock_user
    app.dependency_overrides[api_deps.get_current_tenant] = lambda: "default"

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    # 清理
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def db_engine():
    """创建内存 SQLite 引擎（服务层测试专用）。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """创建测试数据库会话。"""
    session_factory = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session


@pytest.fixture
def mock_llm_response() -> dict[str, Any]:
    """Mock LLM 调用的默认响应。"""
    return {
        "messages": [
            type(
                "MockMessage",
                (),
                {"content": "这是一个模拟的 AI 回复", "type": "ai"},
            )()
        ],
        "token_usage": {
            "call_count": 1,
            "total_tokens": 150,
            "prompt_tokens": 50,
            "completion_tokens": 100,
        },
        "metadata": {},
    }
