from __future__ import annotations

import asyncio
import time

import pytest

from src.execution.order_tracker import OrderTracker
from src.models.execution import OrderRequest
from src.models.market import Exchange
from src.models.orders import OrderSide, OrderStatus, OrderType


def _req(
    symbol: str = "BTCUSDT",
    side: OrderSide = OrderSide.BUY,
    qty: float = 0.01,
    price: float = 50_000.0,
    order_type: OrderType = OrderType.POST_ONLY,
    client_id: str | None = None,
) -> OrderRequest:
    return OrderRequest(
        symbol=symbol,
        side=side,
        qty=qty,
        order_type=order_type,
        client_order_id=client_id or f"test_{symbol}_{int(time.time() * 1000)}",
        price=price,
        category="linear",
    )


# ── register ──────────────────────────────────────────────────────────────────

def test_register_creates_pending_order():
    t = OrderTracker()
    req = _req(client_id="cid1")
    order = t.register(req)
    assert order.status == OrderStatus.PENDING
    assert order.client_order_id == "cid1"
    assert order.qty == 0.01
    assert order.filled_qty == 0.0


def test_register_returns_same_as_get():
    t = OrderTracker()
    req = _req(client_id="cid2")
    order = t.register(req)
    assert t.get("cid2") is order


def test_register_no_active_before_new():
    t = OrderTracker()
    t.register(_req(client_id="cid3"))
    # PENDING is not "active" (not NEW or PARTIALLY_FILLED)
    assert len(t.active_orders()) == 0


# ── on_new ────────────────────────────────────────────────────────────────────

def test_on_new_transitions_to_new():
    t = OrderTracker()
    t.register(_req(client_id="cid4"))
    t.on_new("cid4", "exchange_001", ts_ms=1000)
    order = t.get("cid4")
    assert order.status == OrderStatus.NEW
    assert order.order_id == "exchange_001"


def test_on_new_makes_active():
    t = OrderTracker()
    t.register(_req(client_id="cid5"))
    t.on_new("cid5", "ex002", ts_ms=1000)
    assert len(t.active_orders()) == 1


def test_on_new_ignored_for_unknown_id():
    t = OrderTracker()
    t.on_new("nonexistent", "ex999", ts_ms=0)  # should not raise


# ── on_fill ───────────────────────────────────────────────────────────────────

def test_on_fill_partial():
    t = OrderTracker()
    t.register(_req(client_id="cid6", qty=1.0))
    t.on_new("cid6", "ex003", ts_ms=0)
    t.on_fill("cid6", filled_qty=0.5, avg_price=50_000.0, is_fully_filled=False, ts_ms=1000)
    order = t.get("cid6")
    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert order.filled_qty == pytest.approx(0.5)
    assert order.avg_fill_price == pytest.approx(50_000.0)


def test_on_fill_full():
    t = OrderTracker()
    t.register(_req(client_id="cid7", qty=0.01))
    t.on_new("cid7", "ex004", ts_ms=0)
    t.on_fill("cid7", filled_qty=0.01, avg_price=51_000.0, is_fully_filled=True, ts_ms=2000)
    order = t.get("cid7")
    assert order.status == OrderStatus.FILLED
    assert order.is_terminal


def test_on_fill_ignored_after_terminal():
    t = OrderTracker()
    t.register(_req(client_id="cid8"))
    t.on_new("cid8", "ex005", ts_ms=0)
    t.on_cancel("cid8", ts_ms=100)
    t.on_fill("cid8", filled_qty=0.01, avg_price=50_000.0, is_fully_filled=True, ts_ms=200)
    assert t.get("cid8").status == OrderStatus.CANCELLED


# ── on_cancel / on_reject ──────────────────────────────────────────────────────

def test_on_cancel_transitions():
    t = OrderTracker()
    t.register(_req(client_id="cid9"))
    t.on_new("cid9", "ex006", ts_ms=0)
    t.on_cancel("cid9", ts_ms=500)
    assert t.get("cid9").status == OrderStatus.CANCELLED
    assert t.get("cid9").is_terminal


def test_on_reject_transitions():
    t = OrderTracker()
    t.register(_req(client_id="cid10"))
    t.on_new("cid10", "ex007", ts_ms=0)
    t.on_reject("cid10", ts_ms=500)
    assert t.get("cid10").status == OrderStatus.REJECTED


# ── remaining_qty ─────────────────────────────────────────────────────────────

def test_remaining_qty_after_partial():
    t = OrderTracker()
    t.register(_req(client_id="cid11", qty=1.0))
    t.on_new("cid11", "ex008", ts_ms=0)
    t.on_fill("cid11", filled_qty=0.3, avg_price=50_000.0, is_fully_filled=False, ts_ms=100)
    assert t.get("cid11").remaining_qty == pytest.approx(0.7)


# ── active_orders ─────────────────────────────────────────────────────────────

def test_active_orders_only_new_and_partial():
    t = OrderTracker()
    for i, status_fn in enumerate([
        lambda cid: None,                       # PENDING → not active
        lambda cid: t.on_new(cid, f"ex{i}", 0), # NEW → active
    ]):
        cid = f"cid_active_{i}"
        t.register(_req(client_id=cid))
        status_fn(cid)

    assert len(t.active_orders()) == 1


def test_active_orders_excludes_terminal():
    t = OrderTracker()
    t.register(_req(client_id="cid_t1"))
    t.on_new("cid_t1", "ex_t1", 0)
    t.on_cancel("cid_t1", 0)
    assert len(t.active_orders()) == 0


# ── is_stale ──────────────────────────────────────────────────────────────────

def test_is_stale_after_timeout():
    t = OrderTracker()
    t.register(_req(client_id="cid_s1"))
    t.on_new("cid_s1", "ex_s1", 0)
    order = t.get("cid_s1")
    future_now = order.created_ts + 10_001
    assert t.is_stale("cid_s1", timeout_ms=10_000, now_ms=future_now)


def test_is_stale_within_timeout():
    t = OrderTracker()
    t.register(_req(client_id="cid_s2"))
    t.on_new("cid_s2", "ex_s2", 0)
    order = t.get("cid_s2")
    assert not t.is_stale("cid_s2", timeout_ms=10_000, now_ms=order.created_ts + 5_000)


def test_is_stale_returns_false_for_terminal():
    t = OrderTracker()
    t.register(_req(client_id="cid_s3"))
    t.on_new("cid_s3", "ex_s3", 0)
    t.on_cancel("cid_s3", ts_ms=0)
    assert not t.is_stale("cid_s3", timeout_ms=0, now_ms=999_999_999)


# ── wait_terminal ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wait_terminal_already_filled():
    t = OrderTracker()
    t.register(_req(client_id="cid_w1"))
    t.on_new("cid_w1", "ex_w1", 0)
    t.on_fill("cid_w1", filled_qty=0.01, avg_price=50_000.0, is_fully_filled=True, ts_ms=0)
    result = await t.wait_terminal("cid_w1", timeout_ms=100)
    assert result is True


@pytest.mark.asyncio
async def test_wait_terminal_times_out():
    t = OrderTracker()
    t.register(_req(client_id="cid_w2"))
    t.on_new("cid_w2", "ex_w2", 0)
    result = await t.wait_terminal("cid_w2", timeout_ms=50)  # 50ms — no fill
    assert result is False


@pytest.mark.asyncio
async def test_wait_terminal_wakes_on_cancel():
    t = OrderTracker()
    t.register(_req(client_id="cid_w3"))
    t.on_new("cid_w3", "ex_w3", 0)

    async def _cancel_after():
        await asyncio.sleep(0.01)
        t.on_cancel("cid_w3", ts_ms=1)

    asyncio.create_task(_cancel_after())
    result = await t.wait_terminal("cid_w3", timeout_ms=500)
    assert result is True
    assert t.get("cid_w3").status == OrderStatus.CANCELLED


@pytest.mark.asyncio
async def test_wait_terminal_wakes_on_fill():
    t = OrderTracker()
    t.register(_req(client_id="cid_w4", qty=0.01))
    t.on_new("cid_w4", "ex_w4", 0)

    async def _fill_after():
        await asyncio.sleep(0.01)
        t.on_fill("cid_w4", filled_qty=0.01, avg_price=50_000.0, is_fully_filled=True, ts_ms=1)

    asyncio.create_task(_fill_after())
    result = await t.wait_terminal("cid_w4", timeout_ms=500)
    assert result is True
    assert t.get("cid_w4").status == OrderStatus.FILLED
