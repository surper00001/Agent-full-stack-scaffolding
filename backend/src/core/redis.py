"""Redis 客户端模块。"""

from redis.asyncio import Redis

from src.core.config import get_settings

_redis: Redis | None = None


async def get_redis() -> Redis:
    """获取 Redis 异步客户端（单例）。"""
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = Redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global _redis
    if _redis is not None:
        await _redis.close()
        _redis = None
