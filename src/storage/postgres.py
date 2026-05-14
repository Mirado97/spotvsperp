from __future__ import annotations

import asyncpg

from src.core.logging_setup import get_logger

logger = get_logger(__name__)


class PostgresPool:
    """
    Thin wrapper around asyncpg.Pool.

    Usage:
        pool = PostgresPool(dsn)
        await pool.connect()
        await pool.execute("INSERT INTO ...")
        await pool.close()
    """

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min = min_size
        self._max = max_size
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self._dsn,
            min_size=self._min,
            max_size=self._max,
            command_timeout=10.0,
        )
        logger.info("postgres.connected", min=self._min, max=self._max)

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            logger.info("postgres.closed")

    async def execute(self, sql: str, *args) -> str:
        async with self._pool.acquire() as conn:
            return await conn.execute(sql, *args)

    async def fetch(self, sql: str, *args) -> list[asyncpg.Record]:
        async with self._pool.acquire() as conn:
            return await conn.fetch(sql, *args)

    async def fetchrow(self, sql: str, *args) -> asyncpg.Record | None:
        async with self._pool.acquire() as conn:
            return await conn.fetchrow(sql, *args)

    async def fetchval(self, sql: str, *args):
        async with self._pool.acquire() as conn:
            return await conn.fetchval(sql, *args)

    async def apply_schema(self, schema_sql: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(schema_sql)
        logger.info("postgres.schema_applied")
