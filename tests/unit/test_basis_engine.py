from __future__ import annotations

import pytest

from src.basis.engine import _make_basis_snapshot, _make_carry_metrics, _make_signal
from src.basis.history import BasisHistory
from src.models.funding import FundingRate
from src.models.market import Exchange, InstrumentType, Ticker


def _ticker(
    symbol: str,
    price: float,
    instrument_type: InstrumentType,
    ts_ms: int = 1_000,
) -> Ticker:
    return Ticker(
        exchange=Exchange.BYBIT,
        symbol=symbol,
        instrument_type=instrument_type,
        bid=price - 0.5,
        ask=price + 0.5,
        last=price,
        volume_24h=10_000.0,
        ts_ms=ts_ms,
    )


def _funding(rate: float = 0.0001, predicted: float = 0.00012) -> FundingRate:
    return FundingRate(
        exchange=Exchange.BYBIT,
        symbol="BTCUSDT",
        rate=rate,
        predicted=predicted,
        next_funding_ts=9_999_999,
        interval_h=8,
        ts_ms=1_000,
    )


# ── _make_basis_snapshot ──────────────────────────────────────────────────────

def test_basis_positive_perp_premium():
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL)
    fr = _funding(rate=0.0001)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, fr, ts_ms=2_000)

    assert snap.basis == pytest.approx(0.001, rel=1e-4)
    assert snap.basis_bps == pytest.approx(10.0, rel=1e-4)
    assert snap.perp_premium == pytest.approx(100.0, rel=1e-4)
    assert snap.funding_rate == pytest.approx(0.0001)
    assert snap.funding_yield_ann == pytest.approx(0.0001 * 1095)
    assert snap.ts_ms == 2_000


def test_basis_negative_perp_discount():
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 99_900.0, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, None, ts_ms=1_000)

    assert snap.basis < 0
    assert snap.basis_bps < 0
    assert snap.perp_premium < 0
    assert snap.funding_rate == 0.0
    assert snap.funding_yield_ann == 0.0


def test_basis_zero_spot_mid():
    spot = _ticker("X", 0.0, InstrumentType.SPOT)
    perp = _ticker("X", 100.0, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "X", spot, perp, None, ts_ms=0)
    assert snap.basis == 0.0


def test_basis_annualized_formula():
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, None, ts_ms=0)
    assert snap.annualized_basis == pytest.approx(snap.basis * 1095, rel=1e-6)


# ── _make_carry_metrics ───────────────────────────────────────────────────────

def test_carry_gross_formula():
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, _funding(0.0001), ts_ms=0)
    carry = _make_carry_metrics(snap, holding_period_h=168.0)

    expected_gross = snap.funding_yield_ann + snap.annualized_basis
    assert carry.gross_carry_ann == pytest.approx(expected_gross, rel=1e-6)
    assert carry.gross_carry_bps_ann == pytest.approx(expected_gross * 10_000, rel=1e-6)


def test_carry_net_less_than_gross():
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, _funding(0.0001), ts_ms=0)
    carry = _make_carry_metrics(snap, holding_period_h=168.0)

    assert carry.net_carry_ann < carry.gross_carry_ann
    assert carry.estimated_cost_ann > 0


def test_carry_longer_holding_lower_cost():
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, _funding(0.0001), ts_ms=0)

    carry_7d = _make_carry_metrics(snap, holding_period_h=168.0)
    carry_30d = _make_carry_metrics(snap, holding_period_h=720.0)

    assert carry_30d.estimated_cost_ann < carry_7d.estimated_cost_ann


# ── _make_signal ──────────────────────────────────────────────────────────────

def _ready_history(mean: float = 0.001, std: float = 0.0005, n: int = 50) -> BasisHistory:
    import numpy as np
    rng = np.random.default_rng(99)
    h = BasisHistory(window=200)
    for v in rng.normal(mean, std, n):
        h.push(float(v))
    return h


def test_signal_no_signal_within_band():
    history = _ready_history(mean=0.001, std=0.0005)
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL)  # basis ≈ 0.001
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, None, ts_ms=0)
    sig = _make_signal("BYBIT", "BTCUSDT", snap, history, threshold=2.0, ts_ms=0)
    # basis ≈ mean → z ≈ 0 → no signal
    assert not sig.is_signal or sig.direction == "none"


def test_signal_long_carry_when_basis_elevated():
    history = _ready_history(mean=0.001, std=0.0005)
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 102_000.0, InstrumentType.PERPETUAL)  # basis = 0.02, very high
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, None, ts_ms=0)
    sig = _make_signal("BYBIT", "BTCUSDT", snap, history, threshold=2.0, ts_ms=0)
    assert sig.is_signal
    assert sig.direction == "long_carry"
    assert sig.z_score > 2.0
    assert sig.signal_strength > 1.0


def test_signal_short_carry_when_basis_depressed():
    history = _ready_history(mean=0.001, std=0.0005)
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp = _ticker("BTCUSDT", 99_000.0, InstrumentType.PERPETUAL)  # basis = -0.01
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, None, ts_ms=0)
    sig = _make_signal("BYBIT", "BTCUSDT", snap, history, threshold=2.0, ts_ms=0)
    assert sig.is_signal
    assert sig.direction == "short_carry"
    assert sig.z_score < -2.0


def test_signal_strength_at_threshold():
    history = _ready_history(mean=0.001, std=0.0005)
    # Craft a basis exactly at 2σ above mean
    snap_basis = history.mean + 2.0 * history.std
    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT)
    perp_price = 100_000.0 * (1 + snap_basis)
    perp = _ticker("BTCUSDT", perp_price, InstrumentType.PERPETUAL)
    snap = _make_basis_snapshot("BYBIT", "BTCUSDT", spot, perp, None, ts_ms=0)
    sig = _make_signal("BYBIT", "BTCUSDT", snap, history, threshold=2.0, ts_ms=0)
    assert sig.signal_strength == pytest.approx(1.0, abs=0.05)


# ── BasisEngine integration ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_computes_after_both_tickers():
    from src.basis.engine import BasisEngine
    from src.core.bus import MarketDataBus

    bus = MarketDataBus()
    engine = BasisEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT"])

    import asyncio

    # yield to event loop so consumer tasks can start and call bus.subscribe()
    await asyncio.sleep(0)

    basis_q = bus.subscribe("basis.BYBIT.BTCUSDT")

    spot = _ticker("BTCUSDT", 100_000.0, InstrumentType.SPOT, ts_ms=1_000)
    perp = _ticker("BTCUSDT", 100_100.0, InstrumentType.PERPETUAL, ts_ms=1_000)

    bus.publish("ticker.BYBIT.BTCUSDT.SPOT", spot)
    bus.publish("ticker.BYBIT.BTCUSDT.PERP", perp)

    snap = await asyncio.wait_for(basis_q.get(), timeout=1.0)
    assert snap.symbol == "BTCUSDT"
    assert snap.basis == pytest.approx(0.001, rel=1e-3)

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_no_output_with_only_spot():
    from src.basis.engine import BasisEngine
    from src.core.bus import MarketDataBus

    import asyncio

    bus = MarketDataBus()
    engine = BasisEngine(bus=bus, exchange="BYBIT")
    await engine.start(["ETHUSDT"])

    basis_q = bus.subscribe("basis.BYBIT.ETHUSDT")
    spot = _ticker("ETHUSDT", 3_000.0, InstrumentType.SPOT, ts_ms=1_000)
    bus.publish("ticker.BYBIT.ETHUSDT.SPOT", spot)

    await asyncio.sleep(0.05)
    assert basis_q.empty()

    await engine.stop()
