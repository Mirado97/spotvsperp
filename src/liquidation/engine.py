from __future__ import annotations

import asyncio

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.liquidation.history import LiquidationHistory, OIHistory
from src.liquidation.models import LiquidationAlert
from src.models.liquidation import LiquidationEvent
from src.models.market import Exchange, OpenInterest

logger = get_logger(__name__)


class LiquidationEngine:
    """
    Async engine that aggregates liquidation events and OI data per symbol,
    publishing LiquidationAlert to the bus on every new liquidation.

    Data flow:
        bus "liquidation.{exchange}.{symbol}" → LiquidationEvent
            → LiquidationHistory.push()
            → LiquidationAlert
            → bus "liq_alert.{exchange}.{symbol}"

        bus "oi.{exchange}.{symbol}" → OpenInterest
            → OIHistory.push()   (alert is re-used on next liquidation)
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        window_ms: int = 300_000,   # 5-minute rolling window
        oi_window: int = 20,        # 20 OI samples for spike detection
    ) -> None:
        self._bus = bus
        self._exchange = exchange
        self._window_ms = window_ms
        self._oi_window = oi_window

        self._liq_histories: dict[str, LiquidationHistory] = {}
        self._oi_histories: dict[str, OIHistory] = {}
        self._latest: dict[str, LiquidationAlert] = {}
        self._tasks: list[asyncio.Task] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._liq_histories[sym] = LiquidationHistory(window_ms=self._window_ms)
            self._oi_histories[sym] = OIHistory(window=self._oi_window)
            self._tasks.append(
                asyncio.create_task(self._consume_liq(sym), name=f"liq_eng_{sym}")
            )
            self._tasks.append(
                asyncio.create_task(self._consume_oi(sym), name=f"liq_oi_{sym}")
            )
        logger.info("liq_engine.started", exchange=self._exchange, symbols=symbols)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("liq_engine.stopped")

    def get_alert(self, symbol: str) -> LiquidationAlert | None:
        return self._latest.get(symbol)

    def get_liq_history(self, symbol: str) -> LiquidationHistory | None:
        return self._liq_histories.get(symbol)

    def get_oi_history(self, symbol: str) -> OIHistory | None:
        return self._oi_histories.get(symbol)

    # ── Consumers ─────────────────────────────────────────────────────────────

    async def _consume_liq(self, symbol: str) -> None:
        q = self._bus.subscribe(f"liquidation.{self._exchange}.{symbol}")
        while True:
            event: LiquidationEvent = await q.get()
            liq = self._liq_histories[symbol]
            liq.push(event)
            alert = _make_alert(event.exchange, symbol, liq, self._oi_histories[symbol], event.ts_ms)
            self._latest[symbol] = alert
            self._bus.publish(f"liq_alert.{self._exchange}.{symbol}", alert)

            if alert.is_cascade:
                logger.warning(
                    "liquidation.cascade",
                    symbol=symbol,
                    total_usd=round(alert.total_liq_usd),
                    rate_per_min=round(alert.liq_rate_per_min),
                    net_pressure=round(alert.net_pressure, 2),
                )
            elif alert.squeeze_side != "neutral":
                logger.warning(
                    "liquidation.squeeze",
                    symbol=symbol,
                    side=alert.squeeze_side,
                    net_pressure=round(alert.net_pressure, 2),
                    event_count=alert.event_count,
                )

    async def _consume_oi(self, symbol: str) -> None:
        q = self._bus.subscribe(f"oi.{self._exchange}.{symbol}")
        while True:
            oi: OpenInterest = await q.get()
            self._oi_histories[symbol].push(oi.oi_value)


# ── Pure computation ───────────────────────────────────────────────────────────

def _make_alert(
    exchange: Exchange,
    symbol: str,
    liq: LiquidationHistory,
    oi: OIHistory,
    ts_ms: int,
) -> LiquidationAlert:
    return LiquidationAlert(
        exchange=exchange,
        symbol=symbol,
        window_ms=liq.window_ms,
        long_liq_usd=liq.long_liq_usd,
        short_liq_usd=liq.short_liq_usd,
        total_liq_usd=liq.total_liq_usd,
        net_pressure=liq.net_pressure,
        squeeze_side=liq.squeeze_side,
        is_cascade=liq.is_cascade,
        liq_rate_per_min=liq.liq_rate_per_min,
        event_count=liq.event_count,
        oi_value=oi.latest,
        oi_change_pct=oi.oi_change_pct,
        is_oi_spike=oi.is_spike,
        ts_ms=ts_ms,
    )
