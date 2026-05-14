from __future__ import annotations

import pytest

from src.liquidation.history import LiquidationHistory, OIHistory
from src.liquidation.models import (
    CASCADE_THRESHOLD_USD,
    OI_SPIKE_THRESHOLD,
    SQUEEZE_THRESHOLD,
)
from src.models.liquidation import LiquidationEvent
from src.models.market import Exchange


def _ev(
    side: str = "long",
    value_usd: float = 10_000.0,
    ts_ms: int = 0,
    price: float = 50_000.0,
) -> LiquidationEvent:
    qty = value_usd / price
    return LiquidationEvent(
        exchange=Exchange.BYBIT,
        symbol="BTCUSDT",
        side=side,
        qty=qty,
        price=price,
        value_usd=value_usd,
        ts_ms=ts_ms,
    )


# ── LiquidationHistory: basic state ──────────────────────────────────────────

def test_empty_history():
    h = LiquidationHistory()
    assert h.event_count == 0
    assert h.long_liq_usd == 0.0
    assert h.short_liq_usd == 0.0
    assert h.total_liq_usd == 0.0
    assert h.net_pressure == 0.0
    assert h.squeeze_side == "neutral"
    assert h.liq_rate_per_min == 0.0
    assert not h.is_cascade


def test_push_increases_count():
    h = LiquidationHistory()
    h.push(_ev(side="long", ts_ms=0))
    h.push(_ev(side="short", ts_ms=1))
    assert h.event_count == 2


# ── Time-window eviction ──────────────────────────────────────────────────────

def test_eviction_removes_old_events():
    h = LiquidationHistory(window_ms=60_000)  # 1 minute window
    h.push(_ev(ts_ms=0))
    h.push(_ev(ts_ms=29_000))
    # push at t=90_000: cutoff = 30_000; t=0 < 30_000 evicted, t=29_000 < 30_000 evicted
    h.push(_ev(ts_ms=90_000))
    assert h.event_count == 1


def test_eviction_keeps_events_within_window():
    h = LiquidationHistory(window_ms=60_000)
    h.push(_ev(ts_ms=0))
    h.push(_ev(ts_ms=59_000))
    # push at t=59_999: t=0 is within window (59_999 - 60_000 = -1 < 0, all in)
    h.push(_ev(ts_ms=59_999))
    assert h.event_count == 3


def test_window_fully_refreshes():
    h = LiquidationHistory(window_ms=10_000)
    for i in range(5):
        h.push(_ev(ts_ms=i * 1_000))
    # push far in future — all old events evicted
    h.push(_ev(ts_ms=1_000_000))
    assert h.event_count == 1


# ── Long/short split ──────────────────────────────────────────────────────────

def test_long_liq_sum():
    h = LiquidationHistory()
    h.push(_ev(side="long", value_usd=100_000, ts_ms=0))
    h.push(_ev(side="long", value_usd=50_000, ts_ms=1))
    h.push(_ev(side="short", value_usd=200_000, ts_ms=2))
    assert h.long_liq_usd == pytest.approx(150_000)
    assert h.short_liq_usd == pytest.approx(200_000)
    assert h.total_liq_usd == pytest.approx(350_000)


# ── Net pressure ──────────────────────────────────────────────────────────────

def test_net_pressure_all_longs():
    h = LiquidationHistory()
    h.push(_ev(side="long", value_usd=100_000, ts_ms=0))
    assert h.net_pressure == pytest.approx(1.0)


def test_net_pressure_all_shorts():
    h = LiquidationHistory()
    h.push(_ev(side="short", value_usd=100_000, ts_ms=0))
    assert h.net_pressure == pytest.approx(-1.0)


def test_net_pressure_balanced():
    h = LiquidationHistory()
    h.push(_ev(side="long", value_usd=100_000, ts_ms=0))
    h.push(_ev(side="short", value_usd=100_000, ts_ms=1))
    assert h.net_pressure == pytest.approx(0.0)


def test_net_pressure_skewed():
    h = LiquidationHistory()
    h.push(_ev(side="long", value_usd=300_000, ts_ms=0))
    h.push(_ev(side="short", value_usd=100_000, ts_ms=1))
    # (300k - 100k) / 400k = 0.5
    assert h.net_pressure == pytest.approx(0.5)


# ── Squeeze detection ─────────────────────────────────────────────────────────

def test_squeeze_side_long_squeeze():
    h = LiquidationHistory()
    # net_pressure > SQUEEZE_THRESHOLD
    h.push(_ev(side="long", value_usd=1_000_000, ts_ms=0))
    h.push(_ev(side="short", value_usd=10_000, ts_ms=1))
    assert h.squeeze_side == "long_squeeze"


def test_squeeze_side_short_squeeze():
    h = LiquidationHistory()
    h.push(_ev(side="short", value_usd=1_000_000, ts_ms=0))
    h.push(_ev(side="long", value_usd=10_000, ts_ms=1))
    assert h.squeeze_side == "short_squeeze"


def test_squeeze_side_neutral_balanced():
    h = LiquidationHistory()
    h.push(_ev(side="long", value_usd=100_000, ts_ms=0))
    h.push(_ev(side="short", value_usd=100_000, ts_ms=1))
    assert h.squeeze_side == "neutral"


def test_squeeze_threshold_boundary():
    h = LiquidationHistory()
    # net_pressure just above SQUEEZE_THRESHOLD → long_squeeze
    total = 100_000.0
    # net = (long - short) / total = SQUEEZE_THRESHOLD + 0.02
    long_val = (SQUEEZE_THRESHOLD + 1.02) / 2 * total
    short_val = total - long_val
    h.push(_ev(side="long", value_usd=long_val, ts_ms=0))
    h.push(_ev(side="short", value_usd=short_val, ts_ms=1))
    assert h.squeeze_side == "long_squeeze"


# ── Cascade detection ─────────────────────────────────────────────────────────

def test_cascade_detected():
    # window_ms=60_000 → 1 min; inject enough USD to exceed threshold
    h = LiquidationHistory(window_ms=60_000)
    h.push(_ev(side="long", value_usd=CASCADE_THRESHOLD_USD * 2, ts_ms=0))
    assert h.is_cascade is True


def test_cascade_not_triggered_small_volume():
    h = LiquidationHistory(window_ms=60_000)
    h.push(_ev(side="long", value_usd=10_000, ts_ms=0))
    assert h.is_cascade is False


def test_liq_rate_per_min_formula():
    h = LiquidationHistory(window_ms=120_000)  # 2-min window
    h.push(_ev(side="long", value_usd=120_000, ts_ms=0))
    # 120_000 USD / 2 min = 60_000 USD/min
    assert h.liq_rate_per_min == pytest.approx(60_000.0)


# ── OIHistory ─────────────────────────────────────────────────────────────────

def test_oi_empty():
    oi = OIHistory()
    assert oi.latest == 0.0
    assert oi.mean == 0.0
    assert oi.oi_change_pct == 0.0
    assert not oi.is_spike


def test_oi_constant_series():
    oi = OIHistory(window=5)
    for _ in range(5):
        oi.push(1_000_000.0)
    assert oi.oi_change_pct == pytest.approx(0.0, abs=1e-9)
    assert not oi.is_spike


def test_oi_spike_detected():
    oi = OIHistory(window=10)
    for _ in range(9):
        oi.push(1_000_000.0)
    # push 10% jump
    oi.push(1_100_000.0)
    # mean is slightly above 1M, change is ~9.5% ≥ 5%
    assert oi.is_spike is True


def test_oi_spike_negative():
    oi = OIHistory(window=10)
    for _ in range(9):
        oi.push(1_000_000.0)
    oi.push(900_000.0)   # -10% drop
    assert oi.is_spike is True


def test_oi_no_spike_small_change():
    oi = OIHistory(window=10)
    for _ in range(9):
        oi.push(1_000_000.0)
    oi.push(1_010_000.0)  # ~1% change — below 5%
    assert not oi.is_spike


def test_oi_window_evicts_oldest():
    oi = OIHistory(window=3)
    oi.push(1_000_000.0)
    oi.push(1_000_000.0)
    oi.push(1_000_000.0)
    oi.push(1_000_000.0)  # oldest evicted, still 3 elements
    assert len(oi._values) == 3
