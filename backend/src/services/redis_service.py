"""
Redis cache service - provides caching layer for embeddings, search results, and rate limiting.
Uses redis-py with connection pooling for performance.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from loguru import logger

from src.core.config import get_settings

# redis-py async import
try:
    import redis.asyncio as aioredis
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    aioredis = None  # type: ignore


class RedisService:
    """Async Redis client wrapper with common cache patterns."""

    _instance: RedisService | None = None
    _client: Any = None

    def __init__(self) -> None:
        self._settings = get_settings()

    @classmethod
    async def get_instance(cls) -> RedisService:
        """Get or create singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
            await cls._instance.connect()
        return cls._instance

    async def connect(self) -> None:
        """Establish Redis connection pool."""
        if not HAS_REDIS:
            logger.warning("redis-py not installed, caching disabled")
            return
        try:
            self._client = aioredis.from_url(  # type: ignore[union-attr]
                self._settings.redis_url,
                encoding="utf-8",
                decode_responses=False,
                max_connections=20,
                socket_timeout=5,
                socket_connect_timeout=5,
                retry_on_timeout=True,
            )
            await self._client.ping()
            logger.info("Redis connected: {}", self._settings.redis_url)
        except Exception as e:
            logger.warning("Redis unavailable (caching disabled): {}", e)
            self._client = None

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
            logger.info("Redis disconnected")

    @property
    def available(self) -> bool:
        """Whether Redis is available."""
        return self._client is not None

    # ---- Cache key helpers ----

    @staticmethod
    def _cache_key(prefix: str, *parts: str) -> str:
        """Build a namespaced cache key."""
        joined = ":".join(parts)
        return f"agent:{prefix}:{joined}"

    @staticmethod
    def _hash_content(content: str) -> str:
        """Hash content for cache key."""
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    # ---- Embedding cache ----

    async def get_embedding(self, model: str, text: str) -> list[float] | None:
        """Get cached embedding vector."""
        if not self._client:
            return None
        key = self._cache_key("emb", model, self._hash_content(text))
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug("Redis get_embedding failed: {}", e)
        return None

    async def set_embedding(
        self, model: str, text: str, vector: list[float], ttl: int = 86400
    ) -> None:
        """Cache embedding vector (default TTL: 24h)."""
        if not self._client:
            return
        key = self._cache_key("emb", model, self._hash_content(text))
        try:
            await self._client.set(key, json.dumps(vector), ex=ttl)
        except Exception as e:
            logger.debug("Redis set_embedding failed: {}", e)

    async def get_embeddings_batch(
        self, model: str, texts: list[str]
    ) -> tuple[dict[int, list[float]], set[int]]:
        """Batch get cached embeddings. Returns (index->vector map, missing indices set)."""
        if not self._client or not texts:
            return {}, set(range(len(texts)))
        try:
            pipe = self._client.pipeline()
            keys = [self._cache_key("emb", model, self._hash_content(t)) for t in texts]
            for key in keys:
                pipe.get(key)
            results = await pipe.execute()

            found: dict[int, list[float]] = {}
            missing: set[int] = set()
            for i, data in enumerate(results):
                if data:
                    found[i] = json.loads(data)
                else:
                    missing.add(i)
            return found, missing
        except Exception as e:
            logger.debug("Redis get_embeddings_batch failed: {}", e)
            return {}, set(range(len(texts)))

    async def set_embeddings_batch(
        self,
        model: str,
        texts: list[str],
        vectors: list[list[float]],
        ttl: int = 86400,
    ) -> None:
        """Batch cache embedding vectors."""
        if not self._client:
            return
        try:
            pipe = self._client.pipeline()
            for text, vector in zip(texts, vectors, strict=False):
                key = self._cache_key("emb", model, self._hash_content(text))
                pipe.set(key, json.dumps(vector), ex=ttl)
            await pipe.execute()
        except Exception as e:
            logger.debug("Redis set_embeddings_batch failed: {}", e)

    # ---- Search cache ----

    async def get_search_result(self, kb_id: str, query: str, top_k: int) -> dict | None:
        """Get cached search result."""
        if not self._client:
            return None
        cache_text = f"{kb_id}:{query}:{top_k}"
        key = self._cache_key("search", self._hash_content(cache_text))
        try:
            data = await self._client.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            logger.debug("Redis get_search_result failed: {}", e)
        return None

    async def set_search_result(
        self, kb_id: str, query: str, top_k: int, result: dict, ttl: int = 300
    ) -> None:
        """Cache search result (default TTL: 5 min)."""
        if not self._client:
            return
        cache_text = f"{kb_id}:{query}:{top_k}"
        key = self._cache_key("search", self._hash_content(cache_text))
        try:
            await self._client.set(key, json.dumps(result, ensure_ascii=False), ex=ttl)
        except Exception as e:
            logger.debug("Redis set_search_result failed: {}", e)

    async def invalidate_kb_cache(self, _kb_id: str) -> None:
        """Invalidate cached search results for a knowledge base."""
        if not self._client:
            return
        try:
            pattern = "agent:search:*"
            cursor = 0
            deleted = 0
            while True:
                cursor, keys = await self._client.scan(cursor, match=pattern, count=100)
                for key in keys:
                    key_str = key.decode() if isinstance(key, bytes) else key
                    await self._client.delete(key_str)
                    deleted += 1
                if cursor == 0:
                    break
            if deleted:
                logger.info("Invalidated {} search cache entries", deleted)
        except Exception as e:
            logger.debug("Redis invalidate_kb_cache failed: {}", e)

    # ---- Rate limiting ----

    async def check_rate_limit(
        self, key: str, max_requests: int, window_sec: int
    ) -> bool:
        """Simple sliding window rate limiter. Returns True if allowed."""
        if not self._client:
            return True
        try:
            now = await self._client.time()
            current = now[0] + now[1] / 1_000_000
            window_start = current - window_sec

            rkey = self._cache_key("rate", key)
            async with self._client.pipeline() as pipe:
                pipe.zremrangebyscore(rkey, 0, window_start)
                pipe.zcard(rkey)
                pipe.zadd(rkey, {str(current): current})
                pipe.expire(rkey, window_sec * 2)
                _, count, _, _ = await pipe.execute()

            return count < max_requests
        except Exception:
            return True  # Allow on Redis failure
