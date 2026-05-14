from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.basis.history import BasisHistory
from src.basis.models import BasisSnapshot, CarryMetrics, MeanReversionSignal
from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.models.funding import FundingRate
from src.models.market import Exchange, InstrumentType, Ticker

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_PERIODS_PER_YEAR = 365.0 * 24 / 8  # 1095 funding periods per year

# Bybit typical round-trip cost (taker spot + taker linear, both sides)
_ROUND_TRIP_COST = 0.0031  # 0.31%


class BasisEngine:
    """
    Async engine that computes basis / carry / mean-reversion signals for
    a list of symbols on one exchange.

    Data flow:
        MarketDataBus (spot ticker + perp ticker + funding)
            → BasisSnapshot  → bus "basis.{exchange}.{symbol}"
            → CarryMetrics   → bus "carry.{exchange}.{symbol}"
            → MeanReversionSignal → bus "signal.{exchange}.{symbol}"

    One set of 3 consumer tasks per symbol. All computation is synchronous
    and non-blocking; tasks only await on queue.get().
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        z_score_threshold: float = 2.0,
        holding_period_h: float = 168.0,   # 7 days for cost annualization
        history_window: int = 200,
    ) -> None:
        self._bus = bus
        self._exchange = exchange
        self._z_threshold = z_score_threshold
        self._holding_h = holding_period_h
        self._history_window = history_window

        self._spot: dict[str, Ticker] = {}
        self._perp: dict[str, Ticker] = {}
        self._funding: dict[str, FundingRate] = {}
        self._histories: dict[str, BasisHistory] = {}

        # Latest computed values — queryable without subscribing to bus
        self._latest_basis: dict[str, BasisSnapshot] = {}
        self._latest_carry: dict[str, CarryMetrics] = {}
        self._latest_signal: dict[str, MeanReversionSignal] = {}

        self._tasks: list[asyncio.Task] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._histories[sym] = BasisHistory(window=self._history_window)
            self._tasks += [
                asyncio.create_task(self._consume_spot(sym),    name=f"basis_spot_{sym}"),
                asyncio.create_task(self._consume_perp(sym),    name=f"basis_perp_{sym}"),
                asyncio.create_task(self._consume_funding(sym), name=f"basis_funding_{sym}"),
            ]
        logger.info("basis_engine.started", exchange=self._exchange, symbols=symbols)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("basis_engine.stopped")

    def get_basis(self, symbol: str) -> BasisSnapshot | None:
        return self._latest_basis.get(symbol)

    def get_carry(self, symbol: str) -> CarryMetrics | None:
        return self._latest_carry.get(symbol)

    def get_signal(self, symbol: str) -> MeanReversionSignal | None:
        return self._latest_signal.get(symbol)

    def get_history(self, symbol: str) -> BasisHistory | None:
        return self._histories.get(symbol)

    # ── Consumers ─────────────────────────────────────────────────────────────

    async def _consume_spot(self, symbol: str) -> None:
        q = self._bus.subscribe(f"ticker.{self._exchange}.{symbol}.SPOT")
        while True:
            ticker: Ticker = await q.get()
            self._spot[symbol] = ticker
            self._compute(symbol, ticker.ts_ms)

    async def _consume_perp(self, symbol: str) -> None:
        q = self._bus.subscribe(f"ticker.{self._exchange}.{symbol}.PERP")
        while True:
            ticker: Ticker = await q.get()
            self._perp[symbol] = ticker
            self._compute(symbol, ticker.ts_ms)

    async def _consume_funding(self, symbol: str) -> None:
        q = self._bus.subscribe(f"funding.{self._exchange}.{symbol}")
        while True:
            fr: FundingRate = await q.get()
            self._funding[symbol] = fr

    # ── Computation (synchronous, non-blocking) ────────────────────────────────

    def _compute(self, symbol: str, ts_ms: int) -> None:
        spot = self._spot.get(symbol)
        perp = self._perp.get(symbol)
        if not spot or not perp:
            return

        # Reject stale pairing (tickers > 5s apart in exchange time)
        if abs(spot.ts_ms - perp.ts_ms) > 5_000:
            return

        funding = self._funding.get(symbol)

        snapshot = _make_basis_snapshot(self._exchange, symbol, spot, perp, funding, ts_ms)
        self._latest_basis[symbol] = snapshot

        history = self._histories[symbol]
        history.push(snapshot.basis)

        self._bus.publish(f"basis.{self._exchange}.{symbol}", snapshot)

        carry = _make_carry_metrics(snapshot, self._holding_h)
        self._latest_carry[symbol] = carry
        self._bus.publish(f"carry.{self._exchange}.{symbol}", carry)

        if history.is_ready:
            signal = _make_signal(
                self._exchange, symbol, snapshot, history,
                self._z_threshold, ts_ms,
            )
            self._latest_signal[symbol] = signal
            if signal.is_signal:
                self._bus.publish(f"signal.{self._exchange}.{symbol}", signal)
                logger.info(
                    "basis_engine.signal",
                    symbol=symbol,
                    direction=signal.direction,
                    z_score=round(signal.z_score, 2),
                    half_life_h=round(signal.half_life_h, 1),
                )


# ── Pure computation functions (testable in isolation) ─────────────────────────

def _make_basis_snapshot(
    exchange_name: str,
    symbol: str,
    spot: Ticker,
    perp: Ticker,
    funding: FundingRate | None,
    ts_ms: int,
) -> BasisSnapshot:
    ex = Exchange(1) if exchange_name == "BYBIT" else Exchange(1)  # extendable

    spot_mid = spot.mid
    perp_mid = perp.mid

    if spot_mid == 0:
        basis = 0.0
    else:
        basis = (perp_mid - spot_mid) / spot_mid

    funding_rate = funding.rate if funding else 0.0
    predicted = funding.predicted if funding else 0.0
    funding_yield_ann = funding.annualized if funding else 0.0

    return BasisSnapshot(
        exchange=ex,
        symbol=symbol,
        spot_mid=spot_mid,
        perp_mid=perp_mid,
        basis=basis,
        basis_bps=basis * 10_000,
        annualized_basis=basis * _PERIODS_PER_YEAR,
        perp_premium=perp_mid - spot_mid,
        funding_rate=funding_rate,
        predicted_funding=predicted,
        funding_yield_ann=funding_yield_ann,
        ts_ms=ts_ms,
    )


def _make_carry_metrics(snap: BasisSnapshot, holding_period_h: float) -> CarryMetrics:
    # Long spot / short perp carry:
    # - Earn funding_yield_ann per year from periodic funding payments
    # - Capture annualized_basis on entry (one-time, annualized by holding period)
    gross = snap.funding_yield_ann + snap.annualized_basis
    gross_bps = gross * 10_000

    # Cost: round-trip fees annualized over the holding period
    holding_periods_per_year = 365.0 * 24 / holding_period_h
    estimated_cost = _ROUND_TRIP_COST * holding_periods_per_year

    net = gross - estimated_cost
    return CarryMetrics(
        exchange=snap.exchange,
        symbol=snap.symbol,
        funding_yield_ann=snap.funding_yield_ann,
        basis_bps=snap.basis_bps,
        gross_carry_ann=gross,
        gross_carry_bps_ann=gross_bps,
        estimated_cost_ann=estimated_cost,
        net_carry_ann=net,
        net_carry_bps_ann=net * 10_000,
        holding_period_h=holding_period_h,
        ts_ms=snap.ts_ms,
    )


def _make_signal(
    exchange_name: str,
    symbol: str,
    snap: BasisSnapshot,
    history: BasisHistory,
    threshold: float,
    ts_ms: int,
) -> MeanReversionSignal:
    ex = Exchange(1)

    z = history.z_score(snap.basis)
    hl = history.half_life_h()
    is_signal = abs(z) >= threshold

    if z >= threshold:
        direction = "long_carry"    # basis elevated → attractive entry for long carry
    elif z <= -threshold:
        direction = "short_carry"   # basis depressed → consider reverse carry
    else:
        direction = "none"

    strength = abs(z) / threshold if threshold > 0 else 0.0

    return MeanReversionSignal(
        exchange=ex,
        symbol=symbol,
        basis_current=snap.basis,
        basis_mean=history.mean,
        basis_std=history.std,
        z_score=z,
        half_life_h=hl,
        is_signal=is_signal,
        direction=direction,
        signal_strength=strength,
        ts_ms=ts_ms,
    )
