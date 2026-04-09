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

    from loguru import logger

    logger.info(f"[启动] {settings.app_name} v0.1.0 启动中...")
    logger.info(f"   环境: {settings.app_env}")
    logger.info(f"   监听: {settings.app_host}:{settings.app_port}")
    logger.info(f"   LLM 提供商: {settings.llm_provider}")
    logger.info(f"   多租户: {'启用' if settings.multi_tenant_enabled else '禁用'}")
    logger.info(f"   监测: {'启用' if settings.monitoring_enabled else '禁用'} ({settings.monitoring_provider})")

    # 开发环境：自动创建数据库表（生产环境请使用 Alembic 迁移）
    if settings.app_env != "production":
        try:
            from src.db.base import Base
            from src.db.session import _engine

            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("   数据库表自动创建/验证完成")
        except Exception as e:
            logger.warning(f"   数据库表自动创建跳过: {e}")

    yield

    # ---- 关闭 ----
    logger.info(f"[关闭] {settings.app_name} 正在关闭...")

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
