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

    启动时：初始化日志、监测、数据库连接
    关闭时：清理资源
    """
    # ---- 启动 ----
    settings = get_settings()
    setup_logging()
    setup_monitoring()

    from loguru import logger

    # Harness 工具注册表 — 注册所有内置系统工具（文件/Shell/网络）
    try:
        from src.harness.tool_registry import register_builtin_tools

        n = register_builtin_tools()
        logger.info(f"   Harness 工具已注册: {n} 个内置工具")
    except Exception as e:
        logger.warning(f"   Harness 工具注册跳过: {e}")

    # HuggingFace 镜像与 Token（Embedding/Reranker 模型下载）
    if settings.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
    hf_token = settings.hf_token.get_secret_value()
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)

    # GPU 配置：CUDA 缓存和显存限制必须在 torch 首次使用前设置
    # PYTORCH_CUDA_ALLOC_CONF 和 TORCH_HOME 必须在 import torch 之前设置！
    _cache_d = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tools", ".cache", "torch",
    )
    os.environ.setdefault("TORCH_HOME", _cache_d)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    _gpu_available = False
    try:
        import torch
        if torch.cuda.is_available():
            _gpu_available = True
            _vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            _gpu_name = torch.cuda.get_device_name(0)
            # 限制显存占用，给桌面/Ollama 留余量
            _mem_frac = settings.kb_gpu_memory_fraction
            torch.cuda.set_per_process_memory_fraction(_mem_frac)
            torch.cuda.empty_cache()
        else:
            _gpu_available = False
    except Exception:
        _gpu_available = False
    logger.info(f"[启动] {settings.app_name} v0.1.0 启动中...")
    logger.info(f"   环境: {settings.app_env}")
    logger.info(f"   Python: {__import__('sys').executable}")
    logger.info(f"   监听: {settings.app_host}:{settings.app_port}")
    logger.info(f"   LLM 提供商: {settings.llm_provider}")
    logger.info(f"   多租户: {'启用' if settings.multi_tenant_enabled else '禁用'}")
    logger.info(f"   监测: {'启用' if settings.monitoring_enabled else '禁用'} ({settings.monitoring_provider})")
    if _gpu_available:
        logger.info(f"   GPU: {_gpu_name} ({_vram_gb:.1f}GB), 显存限制 {_mem_frac*100:.0f}%")
    else:
        logger.info(f"   GPU: 不可用，使用 CPU 推理")

    # 开发环境：自动创建数据库表（生产环境请使用 Alembic 迁移）
    if settings.app_env != "production":
        try:
            # 确保所有模型被导入以注册到 Base.metadata
            import src.models.domain.knowledge_base  # noqa: F401
            import src.models.domain.skill  # noqa: F401
            from src.db.base import Base
            from src.db.session import _engine

            async with _engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("   数据库表自动创建/验证完成")
        except Exception as e:
            logger.warning(f"   数据库表自动创建跳过: {e}")

    # 确保新字段存在（开发环境简易迁移：自动补齐缺失列）
    try:
        from sqlalchemy import text

        from src.db.session import _engine

        async with _engine.begin() as conn:

            async def _add_column_if_missing(
                table: str, column: str, col_def: str,
            ) -> None:
                """安全添加列：先检查是否存在，避免静默失败。"""
                try:
                    result = await conn.execute(
                        text(
                            "SELECT column_name FROM information_schema.columns "
                            "WHERE table_name = :tbl AND column_name = :col"
                        ),
                        {"tbl": table, "col": column},
                    )
                    if result.fetchone() is None:
                        await conn.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                        )
                        logger.info(f"   已添加 {table}.{column} 列")
                except Exception as e:
                    # information_schema 不可用（如 SQLite），回退到 try-except
                    try:
                        await conn.execute(
                            text(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                        )
                        logger.info(f"   已添加 {table}.{column} 列")
                    except Exception:
                        pass  # 列已存在（SQLite 不支持 IF NOT EXISTS）

            await _add_column_if_missing(
                "users", "role",
                "role VARCHAR(16) NOT NULL DEFAULT 'user'",
            )
            await _add_column_if_missing(
                "conversations", "user_id",
                "user_id VARCHAR(64)",
            )
            await _add_column_if_missing(
                "conversations", "knowledge_base_id",
                "knowledge_base_id VARCHAR(64)",
            )
            await _add_column_if_missing(
                "users", "token_quota",
                "token_quota BIGINT",
            )
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

    # 确保默认管理员账号存在（凭据从配置读取，不再硬编码）
    try:
        from sqlalchemy import select

        from src.core.security import hash_password
        from src.db.session import AsyncSessionLocal
        from src.models.domain.user import User

        admin_username = settings.admin_username
        admin_password = settings.admin_password.get_secret_value()
        admin_email = settings.admin_email

        async with AsyncSessionLocal() as seed_session:
            stmt = select(User).where(User.username == admin_username)
            result = await seed_session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                admin = User(
                    username=admin_username,
                    hashed_password=hash_password(admin_password),
                    email=admin_email,
                    is_active=True,
                    is_verified=True,
                    role="admin",
                )
                seed_session.add(admin)
                await seed_session.commit()
                logger.info(f"   默认管理员 {admin_username} 已创建")
            elif existing.role != "admin":
                existing.role = "admin"
                await seed_session.commit()
                logger.info(f"   已将 {admin_username} 提升为管理员")
    except Exception as e:
        logger.warning(f"   管理员种子数据创建跳过: {e}")

    # 确保默认智能体配置存在
    try:
        from sqlalchemy import select

        from src.agents.prompts import (
            CREATIVE_ADVISOR_PROMPT,
            GENERAL_AGENT_PROMPT,
            MINDMAP_SYSTEM_PROMPT,
        )
        from src.db.session import AsyncSessionLocal as _AgentSession
        from src.models.domain.agent import AgentConfig

        async with _AgentSession() as seed_session:
            # 综合智能体（默认）
            stmt = select(AgentConfig).where(
                AgentConfig.agent_type == "general",
                AgentConfig.is_deleted == False,  # noqa: E712
            )
            result = await seed_session.execute(stmt)
            if result.scalar_one_or_none() is None:
                agent = AgentConfig(
                    name="综合智能助手",
                    agent_type="general",
                    system_prompt=GENERAL_AGENT_PROMPT,
                    model_name="deepseek-chat",
                    temperature=0.7,
                    tenant_id="default",
                )
                seed_session.add(agent)
                await seed_session.commit()
                logger.info("   默认智能体「综合智能助手」已创建")

            # 创意导演（专业智能体）
            stmt = select(AgentConfig).where(
                AgentConfig.agent_type == "creative",
                AgentConfig.is_deleted == False,  # noqa: E712
            )
            result = await seed_session.execute(stmt)
            if result.scalar_one_or_none() is None:
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

            # 思维导图助手（专业智能体）
            stmt = select(AgentConfig).where(
                AgentConfig.agent_type == "mindmap",
                AgentConfig.is_deleted == False,  # noqa: E712
            )
            result = await seed_session.execute(stmt)
            if result.scalar_one_or_none() is None:
                agent = AgentConfig(
                    name="思维导图助手",
                    agent_type="mindmap",
                    system_prompt=MINDMAP_SYSTEM_PROMPT,
                    model_name="deepseek-chat",
                    temperature=0.7,
                    tenant_id="default",
                )
                seed_session.add(agent)
                await seed_session.commit()
                logger.info("   默认智能体「思维导图助手」已创建")
    except Exception as e:
        logger.warning(f"   智能体种子数据创建跳过: {e}")

    # LangGraph 检查点（须在事件循环内创建 AsyncSqliteSaver）
    from src.agents.checkpointer import init_checkpointer

    await init_checkpointer()

    # 模型后台预加载——首次推理前自动触发 lazy init，不阻塞启动
    if settings.kb_embedding_model:
        try:
            from src.services.embedding_service import get_embedding_service

            emb_svc = get_embedding_service()
            import asyncio as _asyncio
            import concurrent.futures as _futures

            _pool = _futures.ThreadPoolExecutor(max_workers=1)
            _asyncio.ensure_future(
                _asyncio.get_running_loop().run_in_executor(
                    _pool, emb_svc._lazy_init
                )
            )
            logger.info("   Embedding 模型后台预热已提交")
        except Exception as e:
            logger.warning(f"   Embedding 模型预热失败（知识库功能不可用）: {e}")

    if settings.kb_reranker_model:
        try:
            from src.services.reranker_service import get_reranker_service

            rerank_svc = get_reranker_service()
            import asyncio as _asyncio2
            import concurrent.futures as _futures2

            _pool2 = _futures2.ThreadPoolExecutor(max_workers=1)
            _asyncio2.ensure_future(
                _asyncio2.get_running_loop().run_in_executor(
                    _pool2, rerank_svc._lazy_init
                )
            )
            logger.info("   Reranker 模型后台预热已提交")
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

    # 给 in-flight 请求一点时间完成，避免关闭引擎时报"连接正在使用"
    import asyncio

    await asyncio.sleep(1)

    from src.agents.checkpointer import shutdown_checkpointer

    await shutdown_checkpointer()

    # 关闭数据库连接
    from src.db.session import close_db_engine

    await close_db_engine()

    # 关闭 Redis 连接
    from src.core.redis import close_redis

    await close_redis()

    # 刷新 Langfuse 追踪数据
    from src.monitoring.tracer import get_monitor

    get_monitor().flush()


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
    setup_cors(app)
    app.add_middleware(SecurityHeadersMiddleware)   # 1. 安全头（最外层）
    app.add_middleware(RateLimitMiddleware)         # 2. 限流
    app.add_middleware(RequestLoggingMiddleware)    # 3. 日志
    app.add_middleware(TenantMiddleware)            # 4. 租户（最内层）

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
