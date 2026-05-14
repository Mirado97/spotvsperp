from __future__ import annotations

import asyncio

from src.basis.models import BasisSnapshot
from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.funding.models import FundingAnalysis
from src.risk.models import RiskAlert, RiskSnapshot
from src.monitoring import metrics as m

logger = get_logger(__name__)


class MetricsCollector:
    """
    Subscribes to bus events and updates Prometheus metrics.

    One async task per (exchange, symbol, topic) trio, plus one for
    portfolio-level risk alerts.
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        symbols: list[str] | None = None,
    ) -> None:
        self._bus = bus
        self._exchange = exchange
        self._symbols: list[str] = symbols or []
        self._tasks: list[asyncio.Task] = []

    def start(self) -> None:
        for sym in self._symbols:
            self._tasks += [
                asyncio.create_task(
                    self._collect_basis(sym), name=f"metrics_basis_{sym}"
                ),
                asyncio.create_task(
                    self._collect_funding(sym), name=f"metrics_funding_{sym}"
                ),
            ]
        self._tasks.append(
            asyncio.create_task(
                self._collect_risk_alerts(), name="metrics_risk_alerts"
            )
        )
        self._tasks.append(
            asyncio.create_task(
                self._collect_risk_snapshots(), name="metrics_risk_snapshots"
            )
        )
        logger.info("metrics_collector.started", symbols=len(self._symbols))

    def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        logger.info("metrics_collector.stopped")

    # ── Per-symbol consumers ──────────────────────────────────────────────────

    async def _collect_basis(self, symbol: str) -> None:
        q = self._bus.subscribe(f"basis.{self._exchange}.{symbol}")
        while True:
            snap: BasisSnapshot = await q.get()
            m.basis_bps.labels(self._exchange, symbol).set(snap.basis_bps)
            m.carry_score.labels(self._exchange, symbol).set(snap.carry_score)
            m.annualized_basis.labels(self._exchange, symbol).set(snap.annualized_basis)

    async def _collect_funding(self, symbol: str) -> None:
        q = self._bus.subscribe(f"funding_analysis.{self._exchange}.{symbol}")
        while True:
            analysis: FundingAnalysis = await q.get()
            m.funding_rate.labels(self._exchange, symbol).set(analysis.current_rate)
            m.funding_rate_predicted.labels(self._exchange, symbol).set(
                analysis.predicted_rate
            )
            m.funding_is_extreme.labels(self._exchange, symbol).set(
                1 if analysis.is_extreme else 0
            )
            m.funding_extreme_streak.labels(self._exchange, symbol).set(
                analysis.extreme_streak
            )

    # ── Portfolio-level consumers ─────────────────────────────────────────────

    async def _collect_risk_alerts(self) -> None:
        q = self._bus.subscribe(f"risk_alert.{self._exchange}")
        while True:
            alert: RiskAlert = await q.get()
            m.risk_level.labels(self._exchange).set(alert.level)

    async def _collect_risk_snapshots(self) -> None:
        q = self._bus.subscribe(f"risk_snapshot.{self._exchange}")
        while True:
            snap: RiskSnapshot = await q.get()
            m.drawdown_pct.labels(self._exchange).set(snap.drawdown_pct)
            m.total_exposure_usd.labels(self._exchange).set(snap.total_exposure_usd)
            m.max_delta_usd.labels(self._exchange).set(snap.max_symbol_delta_usd)

    # ── Direct update helpers (called by orchestrator / other components) ─────

    def record_worker_states(self, statuses: list) -> None:
        alive = 0
        for s in statuses:
            m.worker_state.labels(self._exchange, s.symbol).set(s.state)
            if s.is_alive:
                alive += 1
        m.active_workers.labels(self._exchange).set(alive)

    def record_hedge_result(self, symbol: str, success: bool, latency_ms: float) -> None:
        if success:
            m.hedge_success_total.labels(self._exchange, symbol).inc()
        else:
            m.hedge_failure_total.labels(self._exchange, symbol).inc()
        m.hedge_latency_ms.labels(self._exchange, symbol).observe(latency_ms)

    def record_order_placed(self, symbol: str, side: str) -> None:
        m.orders_placed_total.labels(self._exchange, symbol, side).inc()

    def record_order_filled(self, symbol: str) -> None:
        m.orders_filled_total.labels(self._exchange, symbol).inc()

    def record_order_rejected(self, symbol: str) -> None:
        m.orders_rejected_total.labels(self._exchange, symbol).inc()

    def record_ws_reconnect(self) -> None:
        m.ws_reconnects_total.labels(self._exchange).inc()

    def set_ws_connected(self, connected: bool) -> None:
        m.ws_connected.labels(self._exchange).set(1 if connected else 0)

    def set_equity(self, equity: float) -> None:
        m.equity_usd.labels(self._exchange).set(equity)

    def set_balance(self, currency: str, available: float) -> None:
        m.balance_available.labels(self._exchange, currency).set(available)
