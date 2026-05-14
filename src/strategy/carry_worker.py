from __future__ import annotations

import asyncio
import time

from src.basis.models import BasisSnapshot, MeanReversionSignal
from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.execution.hedge_engine import HedgeEngine
from src.funding.models import FundingAnalysis
from src.models.execution import HedgeRequest, HedgeResult
from src.models.orders import OrderSide
from src.risk.engine import RiskEngine
from src.strategy.models import StrategyConfig, WorkerState, WorkerStatus

logger = get_logger(__name__)


class CarryWorker:
    """
    Independent async worker for one symbol.

    State machine:
        SEARCHING → EXECUTING → HOLDING → CLOSING → SEARCHING
        Any state → STOPPED (graceful stop or emergency)
        Any state → FAILED  (set externally by watchdog on max restarts)

    Entry: carry_score >= min_carry_score AND signal z_score >= entry_z_score
    Exit:  mean-reversion (z_score ≤ exit_z_score) OR max_holding_periods OR emergency
    """

    def __init__(
        self,
        config: StrategyConfig,
        bus: MarketDataBus,
        hedge_engine: HedgeEngine,
        risk_engine: RiskEngine,
    ) -> None:
        self._cfg = config
        self._bus = bus
        self._hedge_engine = hedge_engine
        self._risk_engine = risk_engine
        self._sym = config.symbol
        self._exch = config.exchange

        self._state: WorkerState = WorkerState.IDLE
        self._heartbeat: float = time.time()
        self._stop_event: asyncio.Event = asyncio.Event()

        self._latest_basis: BasisSnapshot | None = None
        self._latest_signal: MeanReversionSignal | None = None
        self._latest_funding: FundingAnalysis | None = None

        self._entry_result: HedgeResult | None = None
        self._periods_held: int = 0
        self._total_trades: int = 0
        self._trade_id: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def heartbeat(self) -> float:
        return self._heartbeat

    @property
    def state(self) -> WorkerState:
        return self._state

    def stop(self) -> None:
        self._stop_event.set()

    def fail(self) -> None:
        self._state = WorkerState.FAILED
        self._stop_event.set()

    def status(self) -> WorkerStatus:
        import time as _t
        return WorkerStatus(
            symbol=self._sym,
            state=int(self._state),
            heartbeat=self._heartbeat,
            periods_held=self._periods_held,
            total_trades=self._total_trades,
            restart_count=0,   # watchdog increments separately
            ts_ms=int(_t.time() * 1000),
        )

    # ── Main loop ─────────────────────────────────────────────────────────────

    async def run(self) -> None:
        basis_q = self._bus.subscribe(f"basis.{self._exch}.{self._sym}")
        signal_q = self._bus.subscribe(f"signal.{self._exch}.{self._sym}")
        funding_q = self._bus.subscribe(f"funding_analysis.{self._exch}.{self._sym}")

        self._state = WorkerState.SEARCHING
        logger.info("worker.started", symbol=self._sym)

        try:
            while not self._stop_event.is_set():
                self._heartbeat = time.time()

                # Wait for basis update (primary trigger, timeout=1s to check stop_event)
                try:
                    basis = await asyncio.wait_for(basis_q.get(), timeout=1.0)
                    self._latest_basis = basis
                except asyncio.TimeoutError:
                    continue

                # Drain secondary queues (non-blocking, get latest)
                _drain(signal_q, self, "_latest_signal")
                _drain(funding_q, self, "_latest_funding")

                if self._risk_engine.is_emergency:
                    await self._handle_emergency()
                    break

                if self._state == WorkerState.SEARCHING:
                    await self._check_entry()
                elif self._state == WorkerState.HOLDING:
                    self._periods_held += 1
                    await self._check_exit()
        except asyncio.CancelledError:
            pass
        finally:
            if self._state not in (WorkerState.STOPPED, WorkerState.FAILED):
                self._state = WorkerState.STOPPED
            logger.info("worker.stopped", symbol=self._sym, state=self._state.name)

    # ── Entry ─────────────────────────────────────────────────────────────────

    async def _check_entry(self) -> None:
        basis = self._latest_basis
        funding = self._latest_funding
        signal = self._latest_signal

        if not _should_enter(basis, funding, signal, self._cfg):
            return

        self._state = WorkerState.EXECUTING
        self._trade_id += 1
        request = _make_entry_request(basis, self._cfg, self._trade_id)

        logger.info("worker.entering", symbol=self._sym, carry_score=basis.carry_score)
        result = await self._hedge_engine.execute_hedge(request)

        if result.success:
            self._entry_result = result
            self._periods_held = 0
            self._total_trades += 1
            self._state = WorkerState.HOLDING
            logger.info(
                "worker.entered",
                symbol=self._sym,
                spot_price=result.spot_avg_price,
                perp_price=result.perp_avg_price,
                qty=result.spot_filled_qty,
            )
        else:
            self._state = WorkerState.SEARCHING
            logger.warning("worker.entry_failed", symbol=self._sym, error=result.error)

    # ── Exit ──────────────────────────────────────────────────────────────────

    async def _check_exit(self) -> None:
        basis = self._latest_basis
        signal = self._latest_signal

        if not _should_exit(basis, signal, self._periods_held, self._cfg):
            return

        await self._close_position(urgency="normal")

    async def _handle_emergency(self) -> None:
        logger.error("worker.emergency_stop", symbol=self._sym)
        if self._state == WorkerState.HOLDING and self._entry_result:
            await self._close_position(urgency="aggressive")
        self._state = WorkerState.STOPPED
        self._stop_event.set()

    async def _close_position(self, urgency: str) -> None:
        basis = self._latest_basis
        if basis is None or self._entry_result is None:
            self._state = WorkerState.SEARCHING
            return

        self._state = WorkerState.CLOSING
        request = _make_exit_request(basis, self._cfg, self._trade_id, urgency)

        logger.info("worker.exiting", symbol=self._sym, periods_held=self._periods_held)
        result = await self._hedge_engine.execute_hedge(request)

        if result.success:
            self._entry_result = None
            self._periods_held = 0
            self._state = WorkerState.SEARCHING
            logger.info("worker.exited", symbol=self._sym, basis=result.realized_basis)
        else:
            # Failed to close: remain in HOLDING, retry next period
            self._state = WorkerState.HOLDING
            logger.warning("worker.exit_failed", symbol=self._sym, error=result.error)


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _should_enter(
    basis: BasisSnapshot | None,
    funding: FundingAnalysis | None,
    signal: MeanReversionSignal | None,
    cfg: StrategyConfig,
) -> bool:
    if basis is None:
        return False
    if basis.carry_score < cfg.min_carry_score:
        return False
    if funding is not None and not funding.is_positive_carry:
        return False
    if signal is not None and signal.z_score < cfg.entry_z_score:
        return False
    return True


def _should_exit(
    basis: BasisSnapshot | None,
    signal: MeanReversionSignal | None,
    periods_held: int,
    cfg: StrategyConfig,
) -> bool:
    if periods_held >= cfg.max_holding_periods:
        return True
    if basis is not None and basis.carry_score < cfg.min_carry_score * 0.3:
        return True
    if signal is not None and signal.z_score <= cfg.exit_z_score:
        return True
    return False


def _make_entry_request(basis: BasisSnapshot, cfg: StrategyConfig, trade_id: int) -> HedgeRequest:
    return HedgeRequest(
        spot_symbol=basis.symbol,
        perp_symbol=basis.symbol,
        spot_side=OrderSide.BUY,
        perp_side=OrderSide.SELL,
        qty=cfg.position_qty,
        spot_ref_price=basis.spot_mid,
        perp_ref_price=basis.perp_mid,
        strategy_id=f"{cfg.symbol}_{trade_id}",
        urgency="normal",
    )


def _make_exit_request(
    basis: BasisSnapshot,
    cfg: StrategyConfig,
    trade_id: int,
    urgency: str,
) -> HedgeRequest:
    return HedgeRequest(
        spot_symbol=basis.symbol,
        perp_symbol=basis.symbol,
        spot_side=OrderSide.SELL,
        perp_side=OrderSide.BUY,
        qty=cfg.position_qty,
        spot_ref_price=basis.spot_mid,
        perp_ref_price=basis.perp_mid,
        strategy_id=f"{cfg.symbol}_{trade_id}_exit",
        urgency=urgency,
    )


def _drain(q: asyncio.Queue, obj: object, attr: str) -> None:
    latest = None
    while True:
        try:
            latest = q.get_nowait()
        except asyncio.QueueEmpty:
            break
    if latest is not None:
        setattr(obj, attr, latest)
