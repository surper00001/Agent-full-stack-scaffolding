"""
LangGraph 检查点（Checkpointer）生命周期管理。

AsyncSqliteSaver.from_conn_string() 是 async context manager，不能直接传给 compile()。
在应用 lifespan 中初始化单例，供 BaseAgent 复用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

_checkpointer: Any = None
_conn: Any = None


def get_checkpointer() -> Any:
    """获取全局 checkpointer；未初始化时回退到 MemorySaver。"""
    if _checkpointer is not None:
        return _checkpointer
    return MemorySaver()


async def init_checkpointer() -> None:
    """在 FastAPI lifespan 启动时初始化（须在运行中的事件循环内调用）。"""
    global _checkpointer, _conn

    if _checkpointer is not None:
        return

    from loguru import logger

    from src.core.config import get_settings

    settings = get_settings()
    db_url = settings.checkpoint_db_url
    if db_url.startswith("sqlite:///"):
        db_path = db_url.replace("sqlite:///", "")
    else:
        db_path = db_url

    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        _conn = await aiosqlite.connect(db_path)
        saver = AsyncSqliteSaver(_conn)
        await saver.setup()
        _checkpointer = saver
        logger.info(f"   LangGraph 检查点: SQLite ({db_path})")
    except Exception as e:
        logger.warning(f"   LangGraph 检查点初始化失败，使用内存模式: {e}")
        _checkpointer = MemorySaver()


async def shutdown_checkpointer() -> None:
    """关闭 SQLite 连接并释放 checkpointer。"""
    global _checkpointer, _conn

    if _conn is not None:
        try:
            await _conn.close()
        except Exception:
            pass
    _checkpointer = None
    _conn = None
