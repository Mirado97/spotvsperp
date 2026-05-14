from __future__ import annotations

import json

import redis.asyncio as aioredis

from src.core.logging_setup import get_logger

logger = get_logger(__name__)

# Redis key TTLs (seconds)
_TTL_MARKET = 60      # basis / funding snapshots
_TTL_POSITION = 300   # position state


class RedisClient:
    """
    Thin async Redis wrapper providing cache and pub/sub helpers.

    Usage:
        client = RedisClient("redis://localhost:6379/0")
        await client.connect()
        await client.cache_json("key", {"foo": 1}, ttl_s=60)
        await client.close()
    """

    def __init__(self, url: str = "redis://localhost:6379/0") -> None:
        self._url = url
        self._redis: aioredis.Redis | None = None

    async def connect(self) -> None:
        self._redis = aioredis.from_url(self._url, decode_responses=True)
        await self._redis.ping()
        logger.info("redis.connected", url=self._url)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()
            logger.info("redis.closed")

    # ── Primitive ops ─────────────────────────────────────────────────────────

    async def set(self, key: str, value: str, ttl_s: int | None = None) -> None:
        if ttl_s is not None:
            await self._redis.setex(key, ttl_s, value)
        else:
            await self._redis.set(key, value)

    async def get(self, key: str) -> str | None:
        return await self._redis.get(key)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._redis.delete(*keys)

    async def publish(self, channel: str, message: str) -> int:
        return await self._redis.publish(channel, message)

    # ── JSON cache helpers ────────────────────────────────────────────────────

    async def cache_json(self, key: str, obj: dict, ttl_s: int = _TTL_MARKET) -> None:
        await self.set(key, json.dumps(obj), ttl_s)

    async def get_json(self, key: str) -> dict | None:
        raw = await self.get(key)
        return json.loads(raw) if raw is not None else None

    # ── Domain cache helpers ──────────────────────────────────────────────────

    async def cache_basis(self, exchange: str, symbol: str, data: dict) -> None:
        await self.cache_json(f"basis:{exchange}:{symbol}", data, _TTL_MARKET)

    async def cache_position(self, exchange: str, symbol: str, data: dict) -> None:
        await self.cache_json(f"pos:{exchange}:{symbol}", data, _TTL_POSITION)

    async def cache_balance(self, exchange: str, currency: str, data: dict) -> None:
        await self.cache_json(f"balance:{exchange}:{currency}", data)

    async def get_position(self, exchange: str, symbol: str) -> dict | None:
        return await self.get_json(f"pos:{exchange}:{symbol}")

    async def get_balance(self, exchange: str, currency: str) -> dict | None:
        return await self.get_json(f"balance:{exchange}:{currency}")
