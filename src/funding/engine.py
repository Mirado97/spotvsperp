from __future__ import annotations

import asyncio

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.funding.history import (
    ACCEL_THRESHOLD,
    EXTREME_THRESHOLD,
    FundingHistory,
)
from src.funding.models import FundingAnalysis
from src.models.funding import FundingRate
from src.models.market import Exchange

logger = get_logger(__name__)


class FundingEngine:
    """
    Async engine that maintains funding history and computes analysis for
    each symbol, publishing FundingAnalysis to the bus on every update.

    Data flow:
        bus "funding.{exchange}.{symbol}" → FundingRate
            → FundingHistory.push()
            → FundingAnalysis
            → bus "funding_analysis.{exchange}.{symbol}"
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        history_window: int = 168,    # 56 days × 3 periods/day
        ewma_span: int = 8,            # 64h EWMA half-weight
    ) -> None:
        self._bus = bus
        self._exchange = exchange
        self._window = history_window
        self._ewma_span = ewma_span

        self._histories: dict[str, FundingHistory] = {}
        self._latest: dict[str, FundingAnalysis] = {}
        self._tasks: list[asyncio.Task] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._histories[sym] = FundingHistory(
                window=self._window, ewma_span=self._ewma_span
            )
            self._tasks.append(
                asyncio.create_task(self._consume(sym), name=f"funding_eng_{sym}")
            )
        logger.info("funding_engine.started", exchange=self._exchange, symbols=symbols)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("funding_engine.stopped")

    def get_analysis(self, symbol: str) -> FundingAnalysis | None:
        return self._latest.get(symbol)

    def get_history(self, symbol: str) -> FundingHistory | None:
        return self._histories.get(symbol)

    # ── Consumer ──────────────────────────────────────────────────────────────

    async def _consume(self, symbol: str) -> None:
        q = self._bus.subscribe(f"funding.{self._exchange}.{symbol}")
        while True:
            fr: FundingRate = await q.get()
            history = self._histories[symbol]
            history.push(fr.rate, fr.ts_ms)
            analysis = _make_analysis(fr, history)
            self._latest[symbol] = analysis
            self._bus.publish(f"funding_analysis.{self._exchange}.{symbol}", analysis)

            if analysis.is_extreme:
                logger.warning(
                    "funding.extreme",
                    symbol=symbol,
                    rate=fr.rate,
                    direction=analysis.rate_direction,
                    streak=analysis.extreme_streak,
                    z=round(analysis.z_score, 2),
                )
            if analysis.is_squeeze_risk:
                logger.warning(
                    "funding.squeeze_risk",
                    symbol=symbol,
                    rate=fr.rate,
                    streak=analysis.extreme_streak,
                    accel=analysis.acceleration,
                )


# ── Pure computation ───────────────────────────────────────────────────────────

def _make_analysis(fr: FundingRate, history: FundingHistory) -> FundingAnalysis:
    rate = fr.rate
    accel = history.acceleration
    ci_lo, ci_hi = history.confidence_interval()

    is_extreme = abs(rate) >= EXTREME_THRESHOLD

    if rate > 0:
        rate_direction = "longs_paying"
    elif rate < 0:
        rate_direction = "shorts_paying"
    else:
        rate_direction = "neutral"

    return FundingAnalysis(
        exchange=fr.exchange,
        symbol=fr.symbol,
        current_rate=rate,
        predicted_rate=fr.predicted,
        ewma_rate=history.ewma,
        mean_rate=history.mean,
        std_rate=history.std,
        z_score=history.z_score(rate),
        percentile=history.percentile_of(rate),
        predicted_next=history.predicted_next(fr.predicted),
        ci_lower=ci_lo,
        ci_upper=ci_hi,
        regime=history.regime,
        acceleration=accel,
        is_accelerating=history.is_accelerating,
        acceleration_direction=history.acceleration_direction,
        is_extreme=is_extreme,
        rate_direction=rate_direction,
        extreme_streak=history.extreme_streak,
        annualized_carry=history.annualized_carry(),
        daily_carry=history.daily_carry(),
        ts_ms=fr.ts_ms,
    )
