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


async def get_redis_client() -> Redis | None:
    """获取 Redis 客户端（兼容旧接口名称，async 工厂）。"""
    try:
        return await get_redis()
    except Exception:
        return None


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global _redis
    if _redis is not None:
        try:  # noqa: SIM105
            await _redis.close()
        except (ConnectionResetError, RuntimeError):
            pass  # 事件循环已关闭或连接不可达
        _redis = None
