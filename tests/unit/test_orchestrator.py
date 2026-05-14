from __future__ import annotations

import asyncio

import pytest

from src.core.bus import MarketDataBus
from src.execution.base import BaseExecutor
from src.execution.hedge_engine import HedgeEngine
from src.execution.order_tracker import OrderTracker
from src.models.execution import OrderRequest
from src.models.orders import Order, OrderSide, OrderStatus, OrderType
from src.risk.engine import RiskEngine
from src.risk.models import RiskLimits
from src.strategy.models import StrategyConfig, WorkerState
from src.strategy.orchestrator import StrategyOrchestrator


# ── Fake infrastructure ───────────────────────────────────────────────────────

class AlwaysFillExecutor(BaseExecutor):
    def __init__(self, tracker: OrderTracker, fill_price: float = 50_000.0):
        self._tracker = tracker
        self._fill_price = fill_price

    async def place(self, request: OrderRequest) -> Order:
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
        return None


def _make_engine() -> tuple[HedgeEngine, OrderTracker]:
    tracker = OrderTracker()
    executor = AlwaysFillExecutor(tracker)
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=10, max_reprice_attempts=0)
    return engine, tracker


def _make_orchestrator(bus: MarketDataBus | None = None) -> StrategyOrchestrator:
    b = bus or MarketDataBus()
    engine, _ = _make_engine()
    risk = RiskEngine(bus=b, limits=RiskLimits(), initial_equity=100_000.0)
    return StrategyOrchestrator(
        bus=b,
        hedge_engine=engine,
        risk_engine=risk,
        watchdog_timeout_s=30.0,
        watchdog_interval_s=60.0,  # long interval so watchdog doesn't fire during tests
    )


def _cfg(symbol: str = "BTCUSDT") -> StrategyConfig:
    return StrategyConfig(symbol=symbol)


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_start_creates_workers():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT"), _cfg("ETHUSDT")])
    await asyncio.sleep(0)

    assert orch.worker_count() == 2
    await orch.stop()


@pytest.mark.asyncio
async def test_get_worker_returns_correct_worker():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT"), _cfg("ETHUSDT")])
    await asyncio.sleep(0)

    assert orch.get_worker("BTCUSDT") is not None
    assert orch.get_worker("ETHUSDT") is not None
    assert orch.get_worker("SOLUSDT") is None

    await orch.stop()


@pytest.mark.asyncio
async def test_stop_sets_workers_stopped():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT")])
    await asyncio.sleep(0.05)

    await orch.stop()
    await asyncio.sleep(0.05)

    worker = orch.get_worker("BTCUSDT")
    assert worker.state == WorkerState.STOPPED


@pytest.mark.asyncio
async def test_status_returns_all_workers():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT"), _cfg("ETHUSDT"), _cfg("SOLUSDT")])
    await asyncio.sleep(0)

    statuses = orch.status()
    assert len(statuses) == 3
    symbols = {s.symbol for s in statuses}
    assert symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    await orch.stop()


@pytest.mark.asyncio
async def test_active_count_before_stop():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT"), _cfg("ETHUSDT")])
    await asyncio.sleep(0.05)

    assert orch.active_count() == 2

    await orch.stop()


@pytest.mark.asyncio
async def test_active_count_after_stop():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT")])
    await asyncio.sleep(0.05)

    await orch.stop()
    await asyncio.sleep(0.05)

    assert orch.active_count() == 0


@pytest.mark.asyncio
async def test_empty_start():
    orch = _make_orchestrator()
    await orch.start([])
    await asyncio.sleep(0)

    assert orch.worker_count() == 0
    assert orch.active_count() == 0
    assert orch.status() == []

    await orch.stop()


@pytest.mark.asyncio
async def test_workers_start_in_searching_state():
    orch = _make_orchestrator()
    await orch.start([_cfg("BTCUSDT")])
    await asyncio.sleep(0.05)

    worker = orch.get_worker("BTCUSDT")
    assert worker.state == WorkerState.SEARCHING

    await orch.stop()
