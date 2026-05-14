from __future__ import annotations

import asyncio

from src.basis.models import BasisSnapshot
from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.funding.models import FundingAnalysis
from src.models.liquidation import LiquidationEvent
from src.storage.redis_client import RedisClient
from src.storage.repositories import MarketRepository

logger = get_logger(__name__)


class StorageWriter:
    """
    Subscribes to bus events for a set of symbols and persists them.

    Writes to:
      - Postgres (via MarketRepository)
      - Redis hot cache (latest basis + funding)

    One asyncio task per (exchange, symbol, topic) trio.
    """

    def __init__(
        self,
        bus: MarketDataBus,
        market_repo: MarketRepository,
        redis: RedisClient,
        exchange: str = "BYBIT",
        symbols: list[str] | None = None,
    ) -> None:
        self._bus = bus
        self._market = market_repo
        self._redis = redis
        self._exchange = exchange
        self._symbols: list[str] = symbols or []
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        for sym in self._symbols:
            self._tasks += [
                asyncio.create_task(self._consume_basis(sym), name=f"writer_basis_{sym}"),
                asyncio.create_task(self._consume_funding(sym), name=f"writer_funding_{sym}"),
                asyncio.create_task(self._consume_liq(sym), name=f"writer_liq_{sym}"),
            ]
        logger.info("storage_writer.started", symbols=len(self._symbols))

    def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        logger.info("storage_writer.stopped")

    # ── Consumers ─────────────────────────────────────────────────────────────

    async def _consume_basis(self, symbol: str) -> None:
        q = self._bus.subscribe(f"basis.{self._exchange}.{symbol}")
        while True:
            snap: BasisSnapshot = await q.get()
            try:
                await self._market.insert_basis(snap)
                await self._redis.cache_basis(
                    self._exchange, symbol,
                    {
                        "basis_bps": snap.basis_bps,
                        "carry_score": snap.carry_score,
                        "spot_mid": snap.spot_mid,
                        "perp_mid": snap.perp_mid,
                        "ts_ms": snap.ts_ms,
                    },
                )
            except Exception as exc:
                logger.warning("storage_writer.basis_error", symbol=symbol, error=str(exc))

    async def _consume_funding(self, symbol: str) -> None:
        q = self._bus.subscribe(f"funding_analysis.{self._exchange}.{symbol}")
        while True:
            analysis: FundingAnalysis = await q.get()
            try:
                await self._market.insert_funding(analysis)
            except Exception as exc:
                logger.warning("storage_writer.funding_error", symbol=symbol, error=str(exc))

    async def _consume_liq(self, symbol: str) -> None:
        q = self._bus.subscribe(f"liquidation.{self._exchange}.{symbol}")
        while True:
            event: LiquidationEvent = await q.get()
            try:
                await self._market.insert_liquidation(event)
            except Exception as exc:
                logger.warning("storage_writer.liq_error", symbol=symbol, error=str(exc))
