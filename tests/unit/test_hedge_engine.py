from __future__ import annotations

import asyncio
import time

import pytest

from src.execution.base import BaseExecutor
from src.execution.hedge_engine import HedgeEngine, _aggressive_price, _make_requests
from src.execution.order_tracker import OrderTracker
from src.models.execution import HedgeRequest, OrderRequest
from src.models.market import Exchange
from src.models.orders import Order, OrderSide, OrderStatus, OrderType


# ── FakeExecutor ──────────────────────────────────────────────────────────────

class FakeExecutor(BaseExecutor):
    """
    In-memory executor for deterministic testing.

    fill_mode:
      "immediate" — every placed order fills instantly
      "never"     — orders stay open (test cancellation/repricing paths)
      "cancel"    — placed order is immediately cancelled (rejected)
    """

    def __init__(
        self,
        tracker: OrderTracker,
        fill_mode: str = "immediate",
        fill_price: float = 50_000.0,
    ) -> None:
        self._tracker = tracker
        self._fill_mode = fill_mode
        self._fill_price = fill_price
        self.placed: list[OrderRequest] = []
        self.cancelled: list[str] = []

    async def place(self, request: OrderRequest) -> Order:
        self.placed.append(request)
        order = self._tracker.register(request)
        self._tracker.on_new(request.client_order_id, f"fake_{request.client_order_id}", 0)
        if self._fill_mode == "immediate":
            self._tracker.on_fill(
                request.client_order_id,
                filled_qty=request.qty,
                avg_price=self._fill_price,
                is_fully_filled=True,
                ts_ms=1,
            )
        elif self._fill_mode == "cancel":
            self._tracker.on_cancel(request.client_order_id, ts_ms=1)
        return self._tracker.get(request.client_order_id)

    async def cancel(self, client_order_id: str) -> bool:
        self.cancelled.append(client_order_id)
        order = self._tracker.get(client_order_id)
        if order and not order.is_terminal:
            self._tracker.on_cancel(client_order_id, ts_ms=1)
            return True
        return False

    async def reprice(self, client_order_id: str, new_price: float) -> str | None:
        order = self._tracker.get(client_order_id)
        if order is None or order.is_terminal:
            return None
        await self.cancel(client_order_id)
        import uuid
        new_cid = uuid.uuid4().hex[:32]
        new_req = OrderRequest(
            symbol=order.symbol,
            side=order.side,
            qty=order.remaining_qty,
            order_type=order.order_type,
            client_order_id=new_cid,
            price=new_price,
            category="linear",
        )
        await self.place(new_req)
        return new_cid


def _make_hedge_request(
    urgency: str = "normal",
    qty: float = 0.01,
    spot_price: float = 50_000.0,
    perp_price: float = 50_100.0,
) -> HedgeRequest:
    return HedgeRequest(
        spot_symbol="BTCUSDT",
        perp_symbol="BTCUSDT",
        spot_side=OrderSide.BUY,
        perp_side=OrderSide.SELL,
        qty=qty,
        spot_ref_price=spot_price,
        perp_ref_price=perp_price,
        strategy_id="test_strat",
        urgency=urgency,
    )


# ── _make_requests ────────────────────────────────────────────────────────────

def test_make_requests_normal_uses_post_only():
    req = _make_hedge_request(urgency="normal")
    spot_req, perp_req = _make_requests(req, "spot_cid", "perp_cid")
    assert spot_req.order_type == OrderType.POST_ONLY
    assert perp_req.order_type == OrderType.POST_ONLY
    assert spot_req.category == "spot"
    assert perp_req.category == "linear"


def test_make_requests_aggressive_uses_ioc():
    req = _make_hedge_request(urgency="aggressive")
    spot_req, perp_req = _make_requests(req, "s", "p")
    assert spot_req.order_type == OrderType.IOC
    assert perp_req.order_type == OrderType.IOC


def test_make_requests_sides():
    req = _make_hedge_request()
    spot_req, perp_req = _make_requests(req, "s", "p")
    assert spot_req.side == OrderSide.BUY
    assert perp_req.side == OrderSide.SELL


# ── _aggressive_price ─────────────────────────────────────────────────────────

def test_aggressive_price_buy_moves_up():
    base = 50_000.0
    p1 = _aggressive_price(base, OrderSide.BUY, attempt=1)
    p2 = _aggressive_price(base, OrderSide.BUY, attempt=2)
    assert p1 > base
    assert p2 > p1


def test_aggressive_price_sell_moves_down():
    base = 50_000.0
    p1 = _aggressive_price(base, OrderSide.SELL, attempt=1)
    p2 = _aggressive_price(base, OrderSide.SELL, attempt=2)
    assert p1 < base
    assert p2 < p1


def test_aggressive_price_zero_attempt_no_change():
    assert _aggressive_price(50_000.0, OrderSide.BUY, 0) == pytest.approx(50_000.0)


# ── HedgeEngine: both legs fill immediately ───────────────────────────────────

@pytest.mark.asyncio
async def test_execute_hedge_both_fill():
    tracker = OrderTracker()
    executor = FakeExecutor(tracker, fill_mode="immediate", fill_price=50_000.0)
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=100, max_reprice_attempts=1)

    result = await engine.execute_hedge(_make_hedge_request())

    assert result.success is True
    assert result.spot_filled_qty == pytest.approx(0.01)
    assert result.perp_filled_qty == pytest.approx(0.01)
    assert result.spot_avg_price == pytest.approx(50_000.0)
    assert result.perp_avg_price == pytest.approx(50_000.0)
    assert result.error == ""


# ── HedgeEngine: is_fully_hedged ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_is_fully_hedged_when_both_fill():
    tracker = OrderTracker()
    executor = FakeExecutor(tracker, fill_mode="immediate")
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=50, max_reprice_attempts=1)
    result = await engine.execute_hedge(_make_hedge_request(qty=0.1))
    assert result.is_fully_hedged is True


# ── HedgeEngine: aggressive urgency ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_execute_hedge_aggressive_fills():
    tracker = OrderTracker()
    executor = FakeExecutor(tracker, fill_mode="immediate", fill_price=51_000.0)
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=100)

    result = await engine.execute_hedge(_make_hedge_request(urgency="aggressive"))
    assert result.success is True


# ── HedgeEngine: repricing when order not filled ──────────────────────────────

@pytest.mark.asyncio
async def test_execute_hedge_reprices_on_timeout():
    tracker = OrderTracker()
    placed_prices: list[float] = []

    class PriceCaptureExecutor(FakeExecutor):
        async def place(self, request: OrderRequest) -> Order:
            placed_prices.append(request.price)
            return await super().place(request)

    executor = PriceCaptureExecutor(tracker, fill_mode="immediate")
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=10, max_reprice_attempts=2)

    await engine.execute_hedge(_make_hedge_request())
    # First placement should be at ref price
    assert placed_prices[0] == pytest.approx(50_000.0)  # spot
    assert placed_prices[1] == pytest.approx(50_100.0)  # perp


# ── HedgeEngine: partial fill → error reported ────────────────────────────────

@pytest.mark.asyncio
async def test_execute_hedge_partial_fill_reports_error():
    tracker = OrderTracker()

    fill_spot = True

    class PartialExecutor(FakeExecutor):
        async def place(self, request: OrderRequest) -> Order:
            order = self._tracker.register(request)
            self._tracker.on_new(request.client_order_id, f"fake_{request.client_order_id}", 0)
            # Only fill spot orders (category="spot"), leave perp open
            if request.category == "spot":
                self._tracker.on_fill(
                    request.client_order_id,
                    filled_qty=request.qty,
                    avg_price=self._fill_price,
                    is_fully_filled=True,
                    ts_ms=1,
                )
            # perp stays open → times out in fill_or_reprice
            return self._tracker.get(request.client_order_id)

    executor = PartialExecutor(tracker, fill_mode="never")
    # Very short reprice interval and 0 reprice attempts → fast test
    engine = HedgeEngine(
        executor, tracker,
        reprice_interval_ms=30,
        max_reprice_attempts=0,
        ioc_timeout_ms=30,
    )

    result = await engine.execute_hedge(_make_hedge_request())
    assert result.success is False
    assert result.spot_filled_qty == pytest.approx(0.01)
    assert result.perp_filled_qty == pytest.approx(0.0)
    assert result.error != ""


# ── HedgeEngine: realized_basis ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_realized_basis():
    tracker = OrderTracker()
    spot_price = 50_000.0
    perp_price = 50_100.0

    class DualPriceExecutor(FakeExecutor):
        async def place(self, request: OrderRequest) -> Order:
            order = self._tracker.register(request)
            self._tracker.on_new(request.client_order_id, f"fake_{request.client_order_id}", 0)
            # Fill at category-specific price
            fill_p = spot_price if request.category == "spot" else perp_price
            self._tracker.on_fill(
                request.client_order_id,
                filled_qty=request.qty,
                avg_price=fill_p,
                is_fully_filled=True,
                ts_ms=1,
            )
            return self._tracker.get(request.client_order_id)

    executor = DualPriceExecutor(tracker, fill_mode="immediate")
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=50, max_reprice_attempts=1)
    result = await engine.execute_hedge(_make_hedge_request(
        spot_price=spot_price, perp_price=perp_price,
    ))
    expected_basis = (perp_price - spot_price) / spot_price
    assert result.realized_basis == pytest.approx(expected_basis, rel=1e-6)


# ── HedgeEngine: stop engine cleans up ───────────────────────────────────────

@pytest.mark.asyncio
async def test_no_active_orders_after_successful_hedge():
    tracker = OrderTracker()
    executor = FakeExecutor(tracker, fill_mode="immediate")
    engine = HedgeEngine(executor, tracker, reprice_interval_ms=50, max_reprice_attempts=1)

    await engine.execute_hedge(_make_hedge_request())
    assert len(tracker.active_orders()) == 0
