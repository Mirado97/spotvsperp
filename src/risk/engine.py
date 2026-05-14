from __future__ import annotations

import asyncio
import time

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.funding.models import FundingAnalysis
from src.liquidation.models import CASCADE_THRESHOLD_USD, LiquidationAlert
from src.models.market import Exchange, Ticker
from src.models.orders import Fill
from src.risk.delta_tracker import DeltaTracker
from src.risk.models import RiskAlert, RiskLevel, RiskLimits, RiskSnapshot

logger = get_logger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class RiskEngine:
    """
    Portfolio-level risk guardian.

    Consumers (one per symbol):
      fill.{exchange}.{symbol}               → updates delta, checks limits
      ticker.{exchange}.{symbol}.PERP        → updates mark prices
      funding_analysis.{exchange}.{symbol}   → checks extreme funding streak
      liq_alert.{exchange}.{symbol}          → checks cascade / squeeze

    Publishers:
      risk_alert.{exchange}                  → every alert (WARNING+)
      emergency_stop.{exchange}              → EMERGENCY only (once)
    """

    def __init__(
        self,
        bus: MarketDataBus,
        limits: RiskLimits,
        initial_equity: float,
        exchange: str = "BYBIT",
    ) -> None:
        self._bus = bus
        self._limits = limits
        self._initial_equity = initial_equity
        self._exchange = exchange
        self._exchange_enum = Exchange[exchange]

        self._tracker = DeltaTracker()
        self._total_fees: float = 0.0
        self._emergency: bool = False
        self._latest_alert: RiskAlert | None = None
        self._tasks: list[asyncio.Task] = []

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self, symbols: list[str]) -> None:
        for sym in symbols:
            self._tasks += [
                asyncio.create_task(self._consume_fills(sym),   name=f"risk_fill_{sym}"),
                asyncio.create_task(self._consume_tickers(sym), name=f"risk_tick_{sym}"),
                asyncio.create_task(self._consume_funding(sym), name=f"risk_fund_{sym}"),
                asyncio.create_task(self._consume_liq(sym),     name=f"risk_liq_{sym}"),
            ]
        logger.info("risk_engine.started", exchange=self._exchange, symbols=symbols)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        logger.info("risk_engine.stopped")

    @property
    def is_emergency(self) -> bool:
        return self._emergency

    def reset_emergency(self) -> None:
        self._emergency = False
        logger.info("risk_engine.emergency_reset")

    def latest_alert(self) -> RiskAlert | None:
        return self._latest_alert

    def snapshot(self) -> RiskSnapshot:
        worst_sym, worst_delta = self._tracker.max_delta_usd_symbol()
        level = int(self._latest_alert.level) if self._latest_alert else int(RiskLevel.OK)
        return RiskSnapshot(
            exchange=self._exchange_enum,
            total_exposure_usd=self._tracker.total_exposure_usd(),
            max_symbol_delta_usd=worst_delta,
            worst_symbol=worst_sym,
            drawdown_pct=self._drawdown_pct(),
            risk_level=level,
            is_emergency=self._emergency,
            ts_ms=_now_ms(),
        )

    # ── Consumers ─────────────────────────────────────────────────────────────

    async def _consume_fills(self, symbol: str) -> None:
        q = self._bus.subscribe(f"fill.{self._exchange}.{symbol}")
        while True:
            fill: Fill = await q.get()
            self._tracker.on_fill(fill)
            self._total_fees += fill.fee
            self._run_portfolio_checks(symbol, fill.ts_ms)

    async def _consume_tickers(self, symbol: str) -> None:
        q = self._bus.subscribe(f"ticker.{self._exchange}.{symbol}.PERP")
        while True:
            ticker: Ticker = await q.get()
            self._tracker.on_price(symbol, ticker.mid)
            self._run_portfolio_checks(symbol, ticker.ts_ms)

    async def _consume_funding(self, symbol: str) -> None:
        q = self._bus.subscribe(f"funding_analysis.{self._exchange}.{symbol}")
        while True:
            analysis: FundingAnalysis = await q.get()
            alert = _check_funding_streak(analysis, self._limits, self._exchange_enum)
            if alert:
                self._emit(alert)

    async def _consume_liq(self, symbol: str) -> None:
        q = self._bus.subscribe(f"liq_alert.{self._exchange}.{symbol}")
        while True:
            liq: LiquidationAlert = await q.get()
            alert = _check_liq(liq, self._limits, self._exchange_enum)
            if alert:
                self._emit(alert)

    # ── Checks ────────────────────────────────────────────────────────────────

    def _run_portfolio_checks(self, symbol: str, ts_ms: int) -> None:
        for alert in [
            _check_delta(
                self._exchange_enum, symbol,
                self._tracker.net_delta_usd(symbol),
                self._limits, ts_ms,
            ),
            _check_exposure(
                self._exchange_enum,
                self._tracker.total_exposure_usd(),
                self._limits, ts_ms,
            ),
            _check_drawdown(
                self._exchange_enum,
                self._drawdown_pct(),
                self._limits, ts_ms,
            ),
        ]:
            if alert:
                self._emit(alert)

    def _drawdown_pct(self) -> float:
        if self._initial_equity <= 0:
            return 0.0
        return self._total_fees / self._initial_equity

    def _emit(self, alert: RiskAlert) -> None:
        self._latest_alert = alert
        self._bus.publish(f"risk_alert.{self._exchange}", alert)

        if alert.is_emergency and not self._emergency:
            self._emergency = True
            self._bus.publish(f"emergency_stop.{self._exchange}", alert)
            logger.error(
                "risk.emergency_stop",
                reason=alert.reason,
                symbol=alert.symbol,
                value=alert.value,
            )
        elif alert.level == int(RiskLevel.CRITICAL):
            logger.warning("risk.critical", reason=alert.reason, symbol=alert.symbol, value=alert.value)
        elif alert.level == int(RiskLevel.WARNING):
            logger.info("risk.warning", reason=alert.reason, symbol=alert.symbol, value=alert.value)


# ── Pure check functions ───────────────────────────────────────────────────────

def _level_for_ratio(ratio: float) -> RiskLevel:
    if ratio >= 1.0:
        return RiskLevel.CRITICAL
    if ratio >= 0.8:
        return RiskLevel.WARNING
    return RiskLevel.OK


def _check_delta(
    exchange: Exchange,
    symbol: str,
    delta_usd: float,
    limits: RiskLimits,
    ts_ms: int,
) -> RiskAlert | None:
    if limits.max_delta_usd <= 0:
        return None
    level = _level_for_ratio(abs(delta_usd) / limits.max_delta_usd)
    if level == RiskLevel.OK:
        return None
    return RiskAlert(
        exchange=exchange, level=int(level), reason="delta_exceeded",
        symbol=symbol, value=delta_usd, limit=limits.max_delta_usd, ts_ms=ts_ms,
    )


def _check_exposure(
    exchange: Exchange,
    total_usd: float,
    limits: RiskLimits,
    ts_ms: int,
) -> RiskAlert | None:
    if limits.max_total_exposure_usd <= 0:
        return None
    level = _level_for_ratio(total_usd / limits.max_total_exposure_usd)
    if level == RiskLevel.OK:
        return None
    return RiskAlert(
        exchange=exchange, level=int(level), reason="exposure_exceeded",
        symbol="", value=total_usd, limit=limits.max_total_exposure_usd, ts_ms=ts_ms,
    )


def _check_drawdown(
    exchange: Exchange,
    drawdown_pct: float,
    limits: RiskLimits,
    ts_ms: int,
) -> RiskAlert | None:
    if limits.max_drawdown_pct <= 0:
        return None
    ratio = drawdown_pct / limits.max_drawdown_pct
    if ratio >= 1.0:
        level = RiskLevel.EMERGENCY
    elif ratio >= 0.7:
        level = RiskLevel.CRITICAL
    elif ratio >= 0.5:
        level = RiskLevel.WARNING
    else:
        return None
    return RiskAlert(
        exchange=exchange, level=int(level), reason="drawdown_limit",
        symbol="", value=drawdown_pct, limit=limits.max_drawdown_pct, ts_ms=ts_ms,
    )


def _check_funding_streak(
    analysis: FundingAnalysis,
    limits: RiskLimits,
    exchange: Exchange,
) -> RiskAlert | None:
    if analysis.extreme_streak < limits.funding_extreme_streak_limit:
        return None
    return RiskAlert(
        exchange=exchange, level=int(RiskLevel.WARNING),
        reason="extreme_funding_streak",
        symbol=analysis.symbol,
        value=float(analysis.extreme_streak),
        limit=float(limits.funding_extreme_streak_limit),
        ts_ms=analysis.ts_ms,
    )


def _check_liq(
    liq: LiquidationAlert,
    limits: RiskLimits,
    exchange: Exchange,
) -> RiskAlert | None:
    if liq.is_cascade:
        return RiskAlert(
            exchange=exchange, level=int(RiskLevel.CRITICAL),
            reason="liq_cascade",
            symbol=liq.symbol,
            value=liq.liq_rate_per_min,
            limit=CASCADE_THRESHOLD_USD,
            ts_ms=liq.ts_ms,
        )
    if abs(liq.net_pressure) >= limits.liq_pressure_threshold:
        return RiskAlert(
            exchange=exchange, level=int(RiskLevel.WARNING),
            reason="liq_squeeze",
            symbol=liq.symbol,
            value=liq.net_pressure,
            limit=limits.liq_pressure_threshold,
            ts_ms=liq.ts_ms,
        )
    return None
