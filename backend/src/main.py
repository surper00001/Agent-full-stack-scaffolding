"""
应用入口模块。

FastAPI 应用工厂：配置路由、中间件、异常处理和生命周期事件。
使用 Scalar 作为 API 文档 UI（中文界面）。
"""

import os
from contextlib import asynccontextmanager

# ── CPU 线程限制（必须在任何 torch / paddle 导入之前设置）──
# 24 核 CPU 上 PyTorch 默认全核心并行，多个模型同时跑时 CPU 被打满且因
# cache thrashing 反而更慢。限制每个模型 4 线程，留出余量给系统和其他进程。
_CPU_THREADS = 4
for _env_key in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
    "NUMEXPR_NUM_THREADS",
):
    os.environ.setdefault(_env_key, str(_CPU_THREADS))
# PaddlePaddle 也需要限制，否则 OCR 会独立占满所有核心
os.environ.setdefault("GOTRACEBACK", "crash")  # 不影响线程，只是占位

# 以下导入必须在环境变量设置之后（torch/paddle 需在 import 前设置线程数）
# ruff: noqa: E402
from fastapi import FastAPI, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from scalar_fastapi import get_scalar_api_reference

from src.api.router import api_v1_router
from src.core.config import get_settings
from src.core.exceptions import AppException
from src.middleware.cors import setup_cors
from src.middleware.logging import RequestLoggingMiddleware
from src.middleware.rate_limit import RateLimitMiddleware
from src.middleware.security_headers import SecurityHeadersMiddleware
from src.middleware.tenant import TenantMiddleware
from src.models.schemas.response import ErrorResponse
from src.monitoring.tracer import setup_monitoring
from src.utils.logger import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。

    启动时：初始化日志、监测、数据库连接、种子数据、模型预热
    关闭时：清理资源（检查点、DB、Redis、追踪刷新）
    """
    from src.core.bootstrap import (
        _init_gpu_config,
        check_kb_dependencies,
        init_checkpointer_async,
        init_sandbox_pool,
        seed_admin_user,
        seed_default_agents,
        setup_dev_database,
        setup_harness_tools,
        setup_huggingface,
        submit_model_warmup,
    )
    from src.core.container import init_container

    # ── 启动：Phase 1 — 配置 ────────────────────────────────
    settings = get_settings()
    setup_logging()
    setup_monitoring()

    from src.monitoring.tracing import setup_tracing
    setup_tracing(app)

    gpu_ok, gpu_name, vram_gb, mem_frac = _init_gpu_config()
    setup_huggingface()

    from loguru import logger

    logger.info(f"[启动] {settings.app_name} v0.1.0 启动中...")
    logger.info(f"   环境: {settings.app_env}")
    logger.info(f"   Python: {__import__('sys').executable}")
    logger.info(f"   监听: {settings.app_host}:{settings.app_port}")
    logger.info(f"   LLM 提供商: {settings.llm_provider}")
    logger.info(f"   多租户: {'启用' if settings.multi_tenant_enabled else '禁用'}")
    logger.info(f"   监测: {'启用' if settings.monitoring_enabled else '禁用'} ({settings.monitoring_provider})")
    if gpu_ok:
        logger.info(f"   GPU: {gpu_name} ({vram_gb:.1f}GB), 显存限制 {mem_frac*100:.0f}%")
    else:
        logger.info("   GPU: 不可用，使用 CPU 推理")

    # ── 启动：Phase 2 — 工具 & 基础设施 ──────────────────────
    await init_container(services=["tool_registry"])  # DI 容器初始化（预加载核心注册表）
    setup_harness_tools()
    await init_sandbox_pool()  # 沙箱池预热（非阻塞，失败不影响服务）

    if settings.app_env != "production":
        await setup_dev_database()

    # ── 启动：Phase 3 — 种子数据 ─────────────────────────────
    await seed_admin_user()
    await seed_default_agents()

    # ── 启动：Phase 4 — 检查点 ───────────────────────────────
    await init_checkpointer_async()

    # ── 启动：Phase 5 — 模型预热 & 依赖检测 ──────────────────
    submit_model_warmup()
    check_kb_dependencies()

    yield

    # ── 关闭 ─────────────────────────────────────────────────
    import asyncio

    logger.info(f"[关闭] {settings.app_name} 正在关闭...")
    await asyncio.sleep(1)  # 给 in-flight 请求缓冲时间

    from src.harness.sandbox.manager import shutdown_sandbox_manager
    await shutdown_sandbox_manager()

    from src.agents.checkpointer import shutdown_checkpointer
    await shutdown_checkpointer()

    from src.core.container import shutdown_container
    await shutdown_container()
    from src.db.session import close_db_engine

    await close_db_engine()
    from src.core.redis import close_redis

    await close_redis()
    from src.monitoring.tracer import get_monitor

    get_monitor().flush()

    # 刷新 OpenTelemetry 追踪
    from opentelemetry import trace as otel_trace

    provider = otel_trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis=5000)


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

    # ---- 中间件注册（顺序重要：外→内执行） ----
    app.add_middleware(GZipMiddleware, minimum_size=500)  # 响应压缩
    setup_cors(app)
    app.add_middleware(SecurityHeadersMiddleware)   # 1. 安全头（最外层）
    app.add_middleware(RateLimitMiddleware)         # 2. 限流
    app.add_middleware(RequestLoggingMiddleware)    # 3. 日志
    app.add_middleware(TenantMiddleware)            # 4. 租户（最内层）

    # ---- 异常处理 ----
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException):  # noqa: ARG001
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
    async def general_exception_handler(request: Request, exc: Exception):  # noqa: ARG001
        """兜底异常处理，避免内部错误暴露给客户端。"""
        from loguru import logger

        # 跳过 ASGI 断开连接时的噪音日志
        if isinstance(exc, RuntimeError) and "send" in str(exc).lower():
            return

        logger.exception(f"未处理的异常: {exc}")

        try:
            return JSONResponse(
                status_code=500,
                content=ErrorResponse(
                    success=False,
                    code=50000,
                    message="服务内部错误",
                    detail=str(exc) if settings.app_debug else None,
                ).model_dump(),
            )
        except RuntimeError:
            # 客户端连接已断开，无法发送响应
            return None

    # ---- 路由注册 ----
    app.include_router(api_v1_router)

    # ---- Scalar API 文档（仅非生产环境） ----
    if settings.app_env != "production":

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

