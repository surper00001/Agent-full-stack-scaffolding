"""
Alembic 迁移环境配置。

自动从 src.db.base.Base 读取所有 ORM 模型的 metadata，
支持 PostgreSQL（生产）和 SQLite（开发测试）。
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Alembic Config 对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ---- 导入所有 ORM 模型，确保 metadata 中包含所有表 ----
from src.db.base import Base  # noqa: E402
import src.models.domain.tenant  # noqa: E402, F401
import src.models.domain.user  # noqa: E402, F401
import src.models.domain.refresh_token  # noqa: E402, F401
import src.models.domain.conversation  # noqa: E402, F401
import src.models.domain.agent  # noqa: E402, F401
import src.models.domain.knowledge_base  # noqa: E402, F401
import src.models.domain.skill  # noqa: E402, F401

# 目标元数据
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    离线迁移模式。

    生成 SQL 脚本而不连接数据库，适合审核后手动执行。
    使用方式: alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """在线迁移模式，直接连接数据库执行 DDL。"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
