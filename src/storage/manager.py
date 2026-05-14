from __future__ import annotations

import pathlib

from src.core.logging_setup import get_logger
from src.storage.postgres import PostgresPool
from src.storage.redis_client import RedisClient
from src.storage.repositories import (
    BalanceRepository,
    MarketRepository,
    MetricsRepository,
    PositionRepository,
    TradeRepository,
)

logger = get_logger(__name__)

_SCHEMA_PATH = pathlib.Path(__file__).parent / "schema.sql"


class StorageManager:
    """
    Owns PostgreSQL + Redis connections and exposes typed repositories.

    Usage:
        mgr = StorageManager(postgres_dsn, redis_url)
        await mgr.connect()
        await mgr.apply_schema()
        mgr.trades.insert_fill(...)
        await mgr.close()
    """

    def __init__(self, postgres_dsn: str, redis_url: str) -> None:
        self._pg = PostgresPool(postgres_dsn)
        self._redis = RedisClient(redis_url)

        self.trades = TradeRepository(self._pg)
        self.positions = PositionRepository(self._pg)
        self.market = MarketRepository(self._pg)
        self.balances = BalanceRepository(self._pg)
        self.metrics = MetricsRepository(self._pg)

    @property
    def redis(self) -> RedisClient:
        return self._redis

    async def connect(self) -> None:
        await self._pg.connect()
        await self._redis.connect()
        logger.info("storage.connected")

    async def close(self) -> None:
        await self._pg.close()
        await self._redis.close()
        logger.info("storage.closed")

    async def apply_schema(self) -> None:
        schema_sql = _SCHEMA_PATH.read_text(encoding="utf-8")
        await self._pg.apply_schema(schema_sql)
