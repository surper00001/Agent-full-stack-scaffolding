"""
应用启动引导模块。

将 lifespan 中的初始化逻辑从 main.py 提取到独立模块：
1. Harness 工具注册
2. HuggingFace 镜像/Token 配置
3. GPU 初始化
4. 开发环境数据库自动建表 / 迁移
5. 管理员种子数据
6. 默认 Agent 配置种子数据
7. LangGraph 检查点初始化
8. 模型后台预热
9. 依赖检测

每个步骤独立函数，便于测试和复用。
"""

from __future__ import annotations

import contextlib
import os

from loguru import logger

from src.core.config import get_settings


def _init_gpu_config() -> tuple[bool, str, float, float]:
    """初始化 GPU 配置（必须在 torch 首次导入前调用）。

    Returns:
        (gpu_available, gpu_name, vram_gb, memory_fraction)
    """
    settings = get_settings()
    _cache_d = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "tools", ".cache", "torch",
    )
    os.environ.setdefault("TORCH_HOME", _cache_d)
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

    try:
        import torch
        if torch.cuda.is_available():
            _vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            _gpu_name = torch.cuda.get_device_name(0)
            _mem_frac = settings.kb_gpu_memory_fraction
            torch.cuda.set_per_process_memory_fraction(_mem_frac)
            torch.cuda.empty_cache()
            return True, _gpu_name, _vram_gb, _mem_frac
    except Exception:
        logger.debug("GPU 检测失败，使用 CPU 推理")
    return False, "", 0.0, 0.0


def setup_harness_tools() -> int:
    """注册 Harness 内置系统工具。Returns 注册数量。"""
    try:
        from src.harness.tool_registry import register_builtin_tools

        n = register_builtin_tools()
        logger.info(f"   Harness 工具已注册: {n} 个内置工具")
        return n
    except Exception as e:
        logger.warning(f"   Harness 工具注册跳过: {e}")
        return 0


async def init_sandbox_pool() -> bool:
    """初始化全局沙箱池（启动时预热）。

    Returns:
        True 如果沙箱池成功启动，False 如果降级（不影响服务可用性）。
    """
    try:
        from src.harness.sandbox.manager import init_sandbox_manager

        manager = await init_sandbox_manager()
        stats = manager.stats
        logger.info(
            f"   沙箱池已启动: {stats['pool_size']} 个预创建, "
            f"Docker={'可用' if stats['docker_available'] else '不可用（回退 ProcessSandbox）'}"
        )
        return True
    except Exception as e:
        logger.warning(f"   沙箱池初始化失败（不影响核心功能）: {e}")
        return False


def setup_huggingface() -> None:
    """配置 HuggingFace 镜像与 Token。"""
    settings = get_settings()
    if settings.hf_endpoint:
        os.environ.setdefault("HF_ENDPOINT", settings.hf_endpoint)
    hf_token = settings.hf_token.get_secret_value()
    if hf_token:
        os.environ.setdefault("HF_TOKEN", hf_token)
        os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", hf_token)


async def setup_dev_database() -> None:
    """开发环境：自动创建数据库表和补齐缺失列。"""
    # 确保所有模型被导入以注册到 Base.metadata
    import src.models.domain.knowledge_base  # noqa: F401
    import src.models.domain.skill  # noqa: F401
    from src.db.base import Base
    from src.db.session import _engine

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 简易列迁移（开发环境）
    await _dev_migrate_columns()


async def _dev_migrate_columns() -> None:
    """开发环境自动补齐缺失列和索引。"""
    from sqlalchemy import text

    from src.db.session import _engine

    async def _add_column_if_missing(
        table: str, column: str, col_def: str,
    ) -> None:
        """安全添加列：先检查 information_schema，失败时回退 try-except。"""
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
        except Exception:
            # information_schema 不可用（如 SQLite），回退到 try-except
            with contextlib.suppress(Exception):
                await conn.execute(
                    text(f"ALTER TABLE {table} ADD COLUMN {col_def}")
                )
                logger.info(f"   已添加 {table}.{column} 列")

    try:
        async with _engine.begin() as conn:
            await _add_column_if_missing(
                "users", "role", "role VARCHAR(16) NOT NULL DEFAULT 'user'",
            )
            await _add_column_if_missing(
                "conversations", "user_id", "user_id VARCHAR(64)",
            )
            await _add_column_if_missing(
                "conversations", "knowledge_base_id", "knowledge_base_id VARCHAR(64)",
            )
            await _add_column_if_missing(
                "users", "token_quota", "token_quota BIGINT",
            )
            with contextlib.suppress(Exception):
                await conn.execute(
                    text(
                        "CREATE INDEX IF NOT EXISTS ix_conversations_knowledge_base_id "
                        "ON conversations (knowledge_base_id)"
                    )
                )
    except Exception as e:
        logger.warning(f"   自动迁移跳过: {e}")


async def seed_admin_user() -> None:
    """确保默认管理员账号存在。"""
    settings = get_settings()
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


async def seed_default_agents() -> None:
    """确保默认 Agent 配置存在。"""
    from sqlalchemy import select

    from src.agents.prompts import (
        CREATIVE_ADVISOR_PROMPT,
        GENERAL_AGENT_PROMPT,
        MINDMAP_SYSTEM_PROMPT,
        RESUME_WRITER_PROMPT,
    )
    from src.db.session import AsyncSessionLocal
    from src.models.domain.agent import AgentConfig

    agents = [
        ("general", "综合智能助手", GENERAL_AGENT_PROMPT),
        ("creative", "创意导演·五人顾问团", CREATIVE_ADVISOR_PROMPT),
        ("mindmap", "思维导图助手", MINDMAP_SYSTEM_PROMPT),
        ("resume_writer", "简历顾问", RESUME_WRITER_PROMPT),
    ]

    async with AsyncSessionLocal() as seed_session:
        for agent_type, name, prompt in agents:
            stmt = select(AgentConfig).where(
                AgentConfig.agent_type == agent_type,
                AgentConfig.is_deleted == False,  # noqa: E712
            )
            result = await seed_session.execute(stmt)
            if result.scalar_one_or_none() is None:
                agent = AgentConfig(
                    name=name,
                    agent_type=agent_type,
                    system_prompt=prompt,
                    model_name="deepseek-chat",
                    temperature=0.7,
                    tenant_id="default",
                )
                seed_session.add(agent)
                await seed_session.commit()
                logger.info(f"   默认智能体「{name}」已创建")


async def init_checkpointer_async() -> None:
    """初始化 LangGraph 检查点。"""
    from src.agents.checkpointer import init_checkpointer

    await init_checkpointer()


def submit_model_warmup() -> None:
    """后台提交 Embedding 和 Reranker 模型预热任务。"""
    import asyncio as _asyncio
    import concurrent.futures as _futures

    settings = get_settings()

    if settings.kb_embedding_model:
        try:
            from src.services.embedding_service import get_embedding_service

            emb_svc = get_embedding_service()
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
            _pool2 = _futures.ThreadPoolExecutor(max_workers=1)
            _asyncio2 = __import__("asyncio")
            _asyncio2.ensure_future(
                _asyncio2.get_running_loop().run_in_executor(
                    _pool2, rerank_svc._lazy_init
                )
            )
            logger.info("   Reranker 模型后台预热已提交")
        except Exception as e:
            logger.warning(f"   Reranker 模型预热失败: {e}")


def check_kb_dependencies() -> list[str]:
    """检测知识库文档解析依赖是否完整。"""
    from src.utils.kb_deps import missing_kb_document_deps

    _kb_missing = missing_kb_document_deps()
    if _kb_missing:
        logger.warning(
            "知识库文档解析依赖未安装: {}。请在 backend 目录执行 uv sync，"
            "并用 restart-dev.ps1 启动。",
            ", ".join(_kb_missing),
        )
    else:
        logger.info("   知识库文档解析依赖已就绪 (pdfplumber / pymupdf / python-docx)")
    return _kb_missing
