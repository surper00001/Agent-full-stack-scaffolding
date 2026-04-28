"""
应用入口模块。

FastAPI 应用工厂：配置路由、中间件、异常处理和生命周期事件。
使用 Scalar 作为 API 文档 UI（中文界面）。
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from scalar_fastapi import get_scalar_api_reference

from src.api.router import api_v1_router
from src.core.config import get_settings
from src.core.exceptions import AppException
from src.middleware.cors import setup_cors
from src.middleware.logging import RequestLoggingMiddleware
from src.middleware.tenant import TenantMiddleware
from src.models.schemas.response import ErrorResponse
from src.monitoring.tracer import setup_monitoring
from src.utils.logger import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动时：初始化日志、监测、数据库连接
    关闭时：清理资源
    """
    # ---- 启动 ----
    settings = get_settings()
    setup_logging()
    setup_monitoring()

    # HuggingFace 镜像与 Token（Embedding/Reranker 模型下载）
    import os

    if settings.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
    hf_token = settings.hf_token.get_secret_value()
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)

    from loguru import logger

    logger.info(f"[启动] {settings.app_name} v0.1.0 启动中...")
    logger.info(f"   环境: {settings.app_env}")
    logger.info(f"   Python: {__import__('sys').executable}")
    logger.info(f"   监听: {settings.app_host}:{settings.app_port}")
    logger.info(f"   LLM 提供商: {settings.llm_provider}")
    logger.info(f"   多租户: {'启用' if settings.multi_tenant_enabled else '禁用'}")
    logger.info(f"   监测: {'启用' if settings.monitoring_enabled else '禁用'} ({settings.monitoring_provider})")

    # 开发环境：自动创建数据库表（生产环境请使用 Alembic 迁移）
    if settings.app_env != "production":
        try:
            # 确保所有模型被导入以注册到 Base.metadata
            import src.models.domain.knowledge_base  # noqa: F401
            from src.db.base import Base
            from src.db.session import _engine

            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("   数据库表自动创建/验证完成")
        except Exception as e:
            logger.warning(f"   数据库表自动创建跳过: {e}")

    # 确保新字段存在（开发环境简易迁移：自动补齐缺失列）
    try:
        from src.db.session import _engine
        from sqlalchemy import text

        async with _engine.begin() as conn:
            # users.role
            try:
                await conn.execute(text("ALTER TABLE users ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'user'"))
                logger.info("   已添加 users.role 列")
            except Exception:
                pass  # 列已存在

            # conversations.user_id
            try:
                await conn.execute(text("ALTER TABLE conversations ADD COLUMN user_id VARCHAR(64)"))
                logger.info("   已添加 conversations.user_id 列")
            except Exception:
                pass  # 列已存在

            # conversations.knowledge_base_id
            try:
                await conn.execute(
                    text("ALTER TABLE conversations ADD COLUMN knowledge_base_id VARCHAR(64)")
                )
                logger.info("   已添加 conversations.knowledge_base_id 列")
            except Exception:
                pass  # 列已存在
            try:
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_conversations_knowledge_base_id "
                        "ON conversations (knowledge_base_id)"
                    )
                )
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"   自动迁移跳过: {e}")

    # 确保默认管理员账号存在
    try:
        from src.db.session import AsyncSessionLocal
        from src.core.security import hash_password
        from src.models.domain.user import User
        from sqlalchemy import select

        async with AsyncSessionLocal() as seed_session:
            stmt = select(User).where(User.username == "admin_tt")
            result = await seed_session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                admin = User(
                    username="admin_tt",
                    hashed_password=hash_password("Tt149212!!!"),
                    email="admin@agent-platform.local",
                    is_active=True,
                    is_verified=True,
                    role="admin",
                )
                seed_session.add(admin)
                await seed_session.commit()
                logger.info("   默认管理员 admin_tt 已创建")
            elif existing.role != "admin":
                existing.role = "admin"
                await seed_session.commit()
                logger.info("   已将 admin_tt 提升为管理员")
    except Exception as e:
        logger.warning(f"   管理员种子数据创建跳过: {e}")

    # 确保默认智能体配置存在
    try:
        from src.db.session import AsyncSessionLocal as _AgentSession
        from src.models.domain.agent import AgentConfig
        from src.agents.prompts import CREATIVE_ADVISOR_PROMPT
        from sqlalchemy import select

        async with _AgentSession() as seed_session:
            stmt = select(AgentConfig).where(
                AgentConfig.agent_type == "creative",
                AgentConfig.is_deleted == False,  # noqa: E712
            )
            result = await seed_session.execute(stmt)
            existing_agent = result.scalar_one_or_none()
            if existing_agent is None:
                agent = AgentConfig(
                    name="创意导演·五人顾问团",
                    agent_type="creative",
                    system_prompt=CREATIVE_ADVISOR_PROMPT,
                    model_name="deepseek-chat",
                    temperature=0.7,
                    tenant_id="default",
                )
                seed_session.add(agent)
                await seed_session.commit()
                logger.info("   默认智能体「创意导演·五人顾问团」已创建")
    except Exception as e:
        logger.warning(f"   智能体种子数据创建跳过: {e}")

    # LangGraph 检查点（须在事件循环内创建 AsyncSqliteSaver）
    from src.agents.checkpointer import init_checkpointer

    await init_checkpointer()

    # 预加载 Embedding / Reranker 模型（首次加载阻塞 60-90s，之后瞬时返回）
    if settings.kb_embedding_model:
        try:
            from src.services.embedding_service import get_embedding_service

            emb_svc = get_embedding_service()
            emb_svc._lazy_init()  # 同步阻塞加载，避免 executor 在 Windows 上卡死
            logger.info("   Embedding 模型预热完成")
        except Exception as e:
            logger.warning(f"   Embedding 模型预热失败（知识库功能不可用）: {e}")

    if settings.kb_reranker_model:
        try:
            from src.services.reranker_service import get_reranker_service

            rerank_svc = get_reranker_service()
            rerank_svc._lazy_init()  # 同步阻塞加载
            logger.info("   Reranker 模型预热完成")
        except Exception as e:
            logger.warning(f"   Reranker 模型预热失败: {e}")

    from src.utils.kb_deps import missing_kb_document_deps

    _kb_missing = missing_kb_document_deps()
    if _kb_missing:
        logger.warning(
            "知识库文档解析依赖未安装: {}。请在 backend 目录执行 uv sync，并用 restart-dev.ps1 启动。",
            ", ".join(_kb_missing),
        )
    else:
        logger.info("   知识库文档解析依赖已就绪 (pdfplumber / pymupdf / python-docx)")

    yield

    # ---- 关闭 ----
    logger.info(f"[关闭] {settings.app_name} 正在关闭...")

    from src.agents.checkpointer import shutdown_checkpointer

    await shutdown_checkpointer()

    # 关闭数据库连接
    from src.db.session import close_db_engine

    await close_db_engine()

    # 关闭 Redis 连接
    from src.core.redis import close_redis

    await close_redis()


def create_app() -> FastAPI:
    """
    创建 FastAPI 应用实例（工厂函数）。

    此模式便于在不同环境（开发/测试/生产）中创建独立实例。
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="企业级 AI Agent 后端平台 - 基于 LangChain + LangGraph + FastAPI",
        docs_url=None,   # 禁用默认 Swagger
        redoc_url=None,  # 禁用默认 ReDoc
        lifespan=lifespan,
    )

    # ---- 中间件注册（顺序重要：先注册的先执行） ----
    setup_cors(app)
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TenantMiddleware)

    # ---- 异常处理 ----
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):
        """统一业务异常处理。"""
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(
                success=False,
                code=exc.code,
                message=exc.message,
                detail=exc.detail,
            ).model_dump(),
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """兜底异常处理，避免内部错误暴露给客户端。"""
        from loguru import logger

        logger.exception(f"未处理的异常: {exc}")

        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                code=50000,
                message="服务内部错误",
                detail=str(exc) if settings.app_debug else None,
            ).model_dump(),
        )

    # ---- 路由注册 ----
    app.include_router(api_v1_router)

    # ---- Scalar API 文档 ----
    @app.get("/docs", include_in_schema=False)
    async def scalar_docs():
        """Scalar API 接口文档页面。"""
        return get_scalar_api_reference(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} - API 接口文档",
            dark_mode=True,
            show_sidebar=True,
            hide_download_button=False,
            hide_test_request_button=False,
            hide_models=False,
            default_open_all_tags=True,
        )

    @app.get("/redoc", include_in_schema=False)
    async def scalar_redoc():
        """Scalar API 文档（备用路径）。"""
        return get_scalar_api_reference(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{settings.app_name} - API 接口文档",
            dark_mode=True,
            show_sidebar=True,
        )

    return app


# 应用实例（供 uvicorn 直接导入）
app = create_app()
