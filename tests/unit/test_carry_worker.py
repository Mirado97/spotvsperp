from __future__ import annotations

import asyncio
import time

import pytest

from src.basis.models import BasisSnapshot, MeanReversionSignal
from src.core.bus import MarketDataBus
from src.execution.base import BaseExecutor
from src.execution.hedge_engine import HedgeEngine
from src.execution.order_tracker import OrderTracker
from src.funding.models import FundingAnalysis
from src.models.execution import HedgeRequest, HedgeResult, OrderRequest
from src.models.market import Exchange, InstrumentType
from src.models.orders import Order, OrderSide, OrderStatus, OrderType
from src.risk.engine import RiskEngine
from src.risk.models import RiskLimits
from src.strategy.carry_worker import (
    CarryWorker,
    _should_enter,
    _should_exit,
    _make_entry_request,
    _make_exit_request,
)
from src.strategy.models import StrategyConfig, WorkerState


# ── Fake infrastructure ───────────────────────────────────────────────────────

class AlwaysFillExecutor(BaseExecutor):
    """Fills every order instantly."""
    def __init__(self, tracker: OrderTracker, fill_price: float = 50_000.0):
        self._tracker = tracker
        self._fill_price = fill_price
        self.placed_count = 0

    async def place(self, request: OrderRequest) -> Order:
        self.placed_count += 1
        order = self._tracker.register(request)
        self._tracker.on_new(request.client_order_id, f"fake_{request.client_order_id}", 0)
        self._tracker.on_fill(request.client_order_id, request.qty, self._fill_price, True, 1)
        return self._tracker.get(request.client_order_id)

    async def cancel(self, client_order_id: str) -> bool:
        order = self._tracker.get(client_order_id)
        if order and not order.is_terminal:
            self._tracker.on_cancel(client_order_id, 0)
            return True
        return False

    async def reprice(self, client_order_id: str, new_price: float) -> str | None:
        return None  # No repricing needed when fills are instant


def _make_engine(fill_price: float = 50_000.0) -> tuple[HedgeEngine, OrderTracker]:
    tracker = OrderTracker()
    executor = AlwaysFillExecutor(tracker, fill_price)
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=10, max_reprice_attempts=0)
    return engine, tracker


def _make_risk_engine(bus: MarketDataBus) -> RiskEngine:
    return RiskEngine(bus=bus, limits=RiskLimits(), initial_equity=100_000.0)


def _cfg(**overrides) -> StrategyConfig:
    cfg = StrategyConfig(symbol="BTCUSDT")
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def _basis(
    spot_mid: float = 50_000.0,
    perp_mid: float = 50_100.0,
    funding_rate: float = 0.0001,
) -> BasisSnapshot:
    basis = (perp_mid - spot_mid) / spot_mid
    return BasisSnapshot(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        spot_mid=spot_mid, perp_mid=perp_mid,
        basis=basis, basis_bps=basis * 10_000,
        annualized_basis=basis * 1095,
        perp_premium=perp_mid - spot_mid,
        funding_rate=funding_rate, predicted_funding=funding_rate,
        funding_yield_ann=funding_rate * 1095,
        ts_ms=1,
    )


def _signal(z_score: float = 1.5, direction: str = "long_carry") -> MeanReversionSignal:
    return MeanReversionSignal(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        basis_current=0.002, basis_mean=0.001, basis_std=0.0005,
        z_score=z_score, half_life_h=24.0,
        is_signal=True, direction=direction,
        signal_strength=abs(z_score),
        ts_ms=1,
    )


def _funding(is_positive_carry: bool = True) -> FundingAnalysis:
    rate = 0.0001 if is_positive_carry else -0.0001
    return FundingAnalysis(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        current_rate=rate, predicted_rate=rate, ewma_rate=rate,
        mean_rate=rate, std_rate=0.00005, z_score=1.0, percentile=0.8,
        predicted_next=rate, ci_lower=rate - 0.00005, ci_upper=rate + 0.00005,
        regime="mildly_bullish" if is_positive_carry else "mildly_bearish",
        acceleration=0.0, is_accelerating=False, acceleration_direction="stable",
        is_extreme=False, rate_direction="longs_paying" if is_positive_carry else "shorts_paying",
        extreme_streak=0, annualized_carry=rate * 1095,
        daily_carry=rate * 3, ts_ms=1,
    )


# ── Pure entry/exit logic ─────────────────────────────────────────────────────

def test_should_enter_all_conditions_met():
    cfg = _cfg(min_carry_score=0.05, entry_z_score=1.0)
    assert _should_enter(_basis(), _funding(), _signal(z_score=1.5), cfg)


def test_should_enter_no_basis():
    assert not _should_enter(None, _funding(), _signal(), _cfg())


def test_should_enter_carry_too_low():
    cfg = _cfg(min_carry_score=0.05)
    # carry_score = funding_yield_ann + annualized_basis ≈ 0.033 < 0.05
    b = _basis(spot_mid=50_000.0, perp_mid=50_001.0, funding_rate=0.00001)
    assert not _should_enter(b, _funding(), _signal(), cfg)


def test_should_enter_negative_funding_blocks():
    cfg = _cfg(min_carry_score=0.01)  # low threshold
    b = _basis()
    assert not _should_enter(b, _funding(is_positive_carry=False), _signal(), cfg)


def test_should_enter_low_z_score_blocks():
    cfg = _cfg(entry_z_score=2.0)
    b = _basis()
    assert not _should_enter(b, _funding(), _signal(z_score=1.0), cfg)


def test_should_enter_no_signal_allowed():
    # Signal is optional — None means no filter
    cfg = _cfg(min_carry_score=0.05)
    assert _should_enter(_basis(), _funding(), None, cfg)


def test_should_exit_max_holding():
    cfg = _cfg(max_holding_periods=5)
    assert _should_exit(_basis(), _signal(z_score=1.5), periods_held=5, cfg=cfg)


def test_should_exit_carry_dried_up():
    cfg = _cfg(min_carry_score=0.05)
    # carry_score = 0 + ~0.002 = 0.002 < 0.05 * 0.3 = 0.015 → triggers exit
    b = _basis(spot_mid=50_000.0, perp_mid=50_000.1, funding_rate=0.0)
    assert _should_exit(b, _signal(z_score=1.5), periods_held=0, cfg=cfg)


def test_should_exit_z_score_reverted():
    cfg = _cfg(exit_z_score=0.0)
    assert _should_exit(_basis(), _signal(z_score=0.0), periods_held=0, cfg=cfg)


def test_should_not_exit_good_carry():
    cfg = _cfg(min_carry_score=0.05, max_holding_periods=21, exit_z_score=0.0)
    assert not _should_exit(_basis(), _signal(z_score=1.5), periods_held=5, cfg=cfg)


# ── Request builders ──────────────────────────────────────────────────────────

def test_make_entry_request_sides():
    req = _make_entry_request(_basis(), _cfg(), trade_id=1)
    assert req.spot_side == OrderSide.BUY
    assert req.perp_side == OrderSide.SELL
    assert req.urgency == "normal"


def test_make_exit_request_sides():
    req = _make_exit_request(_basis(), _cfg(), trade_id=1, urgency="normal")
    assert req.spot_side == OrderSide.SELL
    assert req.perp_side == OrderSide.BUY


def test_make_exit_request_aggressive():
    req = _make_exit_request(_basis(), _cfg(), trade_id=1, urgency="aggressive")
    assert req.urgency == "aggressive"


# ── CarryWorker async integration ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_enters_on_good_signals():
    bus = MarketDataBus()
    engine, tracker = _make_engine()
    risk = _make_risk_engine(bus)
    worker = CarryWorker(_cfg(min_carry_score=0.05, entry_z_score=1.0), bus, engine, risk)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0)

    # Publish entry conditions
    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding())
    bus.publish("signal.BYBIT.BTCUSDT", _signal(z_score=2.0))
    bus.publish("basis.BYBIT.BTCUSDT", _basis())
    await asyncio.sleep(0.05)

    assert worker.state == WorkerState.HOLDING

    worker.stop()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_does_not_enter_on_low_carry():
    bus = MarketDataBus()
    engine, _ = _make_engine()
    risk = _make_risk_engine(bus)
    worker = CarryWorker(_cfg(min_carry_score=0.50), bus, engine, risk)  # very high threshold

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0)

    # tiny carry_score ≈ 0.13 < 0.50 threshold
    bus.publish("basis.BYBIT.BTCUSDT", _basis(perp_mid=50_001.0))
    await asyncio.sleep(0.05)

    assert worker.state == WorkerState.SEARCHING

    worker.stop()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_exits_on_max_holding_periods():
    bus = MarketDataBus()
    engine, _ = _make_engine()
    risk = _make_risk_engine(bus)
    worker = CarryWorker(_cfg(min_carry_score=0.05, max_holding_periods=2), bus, engine, risk)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0)

    # Enter
    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding())
    bus.publish("signal.BYBIT.BTCUSDT", _signal(z_score=2.0))
    bus.publish("basis.BYBIT.BTCUSDT", _basis())
    await asyncio.sleep(0.05)
    assert worker.state == WorkerState.HOLDING

    # Publish 2 more basis updates to hit max_holding_periods
    for _ in range(2):
        bus.publish("basis.BYBIT.BTCUSDT", _basis())
        await asyncio.sleep(0.05)

    assert worker.state == WorkerState.SEARCHING

    worker.stop()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_stops_on_stop_event():
    bus = MarketDataBus()
    engine, _ = _make_engine()
    risk = _make_risk_engine(bus)
    worker = CarryWorker(_cfg(), bus, engine, risk)

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.01)
    worker.stop()
    await asyncio.wait_for(task, timeout=2.0)

    assert worker.state == WorkerState.STOPPED


@pytest.mark.asyncio
async def test_worker_heartbeat_updates():
    bus = MarketDataBus()
    engine, _ = _make_engine()
    risk = _make_risk_engine(bus)
    worker = CarryWorker(_cfg(), bus, engine, risk)

    before = worker.heartbeat
    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    after = worker.heartbeat

    assert after >= before

    worker.stop()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_worker_total_trades_increments():
    bus = MarketDataBus()
    engine, _ = _make_engine()
    risk = _make_risk_engine(bus)
    worker = CarryWorker(
        _cfg(min_carry_score=0.05, max_holding_periods=1, exit_z_score=0.5),
        bus, engine, risk,
    )

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0)

    # Enter
    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding())
    bus.publish("signal.BYBIT.BTCUSDT", _signal(z_score=2.0))
    bus.publish("basis.BYBIT.BTCUSDT", _basis())
    await asyncio.sleep(0.05)

    assert worker._total_trades == 1

    worker.stop()
    await asyncio.gather(task, return_exceptions=True)
