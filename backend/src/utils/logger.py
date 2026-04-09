"""
日志工具模块。

基于 loguru 提供统一的日志配置，支持：
- 控制台输出（带颜色）
- 按日期分割的文件日志
- 不同环境下的日志级别切换
"""

import sys
from pathlib import Path

from loguru import logger

from src.core.config import get_settings


def setup_logging() -> None:
    """初始化日志配置，在应用启动时调用一次。"""
    settings = get_settings()

    # 移除默认 handler
    logger.remove()

    # 控制台输出
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
        "<level>{message}</level>"
    )

    # Windows 下 GBK 编码无法处理 emoji，使用 UTF-8
    import io

    utf8_stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    logger.add(
        utf8_stdout,
        format=log_format,
        level="DEBUG" if settings.app_debug else "INFO",
        colorize=True,
        serialize=False,
    )

    # 文件输出（生产环境）
    if settings.app_env == "production":
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} | {message}",
            level="INFO",
            rotation="00:00",  # 每天午夜轮转
            retention="30 days",
            compression="gz",
            serialize=True,
        )

    logger.info(f"日志系统初始化完成 | 环境: {settings.app_env}")


__all__ = ["logger", "setup_logging"]
