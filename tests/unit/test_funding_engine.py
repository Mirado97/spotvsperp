from __future__ import annotations

import asyncio

import pytest

from src.core.bus import MarketDataBus
from src.funding.engine import FundingEngine, _make_analysis
from src.funding.history import (
    ACCEL_THRESHOLD,
    EXTREME_THRESHOLD,
    TYPICAL_RATE,
    FundingHistory,
)
from src.funding.models import FundingAnalysis
from src.models.funding import FundingRate
from src.models.market import Exchange


# ── Helpers ───────────────────────────────────────────────────────────────────

def _rate(
    rate: float = 0.0001,
    predicted: float = 0.0001,
    symbol: str = "BTCUSDT",
    exchange: Exchange = Exchange.BYBIT,
    ts_ms: int = 1_000_000,
) -> FundingRate:
    return FundingRate(
        exchange=exchange,
        symbol=symbol,
        rate=rate,
        predicted=predicted,
        next_funding_ts=ts_ms + 8 * 3_600_000,
        ts_ms=ts_ms,
    )


def _history_with(rates: list[float]) -> FundingHistory:
    h = FundingHistory(window=168, ewma_span=8)
    for i, r in enumerate(rates):
        h.push(r, i * 8 * 3_600_000)
    return h


# ── _make_analysis: basic fields ──────────────────────────────────────────────

def test_make_analysis_basic_fields():
    h = _history_with([0.0001] * 20)
    fr = _rate(rate=0.0001, predicted=0.0001)
    a = _make_analysis(fr, h)
    assert isinstance(a, FundingAnalysis)
    assert a.symbol == "BTCUSDT"
    assert a.exchange == Exchange.BYBIT
    assert a.current_rate == pytest.approx(0.0001)
    assert a.predicted_rate == pytest.approx(0.0001)
    assert a.ts_ms == 1_000_000


def test_make_analysis_rate_direction_longs_paying():
    h = _history_with([0.0001] * 5)
    a = _make_analysis(_rate(rate=0.0002), h)
    assert a.rate_direction == "longs_paying"


def test_make_analysis_rate_direction_shorts_paying():
    h = _history_with([-0.0001] * 5)
    a = _make_analysis(_rate(rate=-0.0002), h)
    assert a.rate_direction == "shorts_paying"


def test_make_analysis_rate_direction_neutral():
    h = _history_with([0.0] * 5)
    a = _make_analysis(_rate(rate=0.0), h)
    assert a.rate_direction == "neutral"


# ── Extreme detection ─────────────────────────────────────────────────────────

def test_make_analysis_is_extreme_true():
    h = _history_with([EXTREME_THRESHOLD * 2] * 5)
    a = _make_analysis(_rate(rate=EXTREME_THRESHOLD * 2), h)
    assert a.is_extreme is True


def test_make_analysis_is_extreme_false():
    h = _history_with([0.0001] * 5)
    a = _make_analysis(_rate(rate=0.0001), h)
    assert a.is_extreme is False


def test_make_analysis_extreme_negative():
    h = _history_with([-EXTREME_THRESHOLD * 2] * 5)
    a = _make_analysis(_rate(rate=-EXTREME_THRESHOLD * 2), h)
    assert a.is_extreme is True


# ── Squeeze risk ──────────────────────────────────────────────────────────────

def test_squeeze_risk_requires_extreme_accelerating_streak():
    h = FundingHistory(window=168, ewma_span=8)
    for _ in range(3):
        h.push(EXTREME_THRESHOLD * 2, 0)
    # After 3 pushes: streak=3, acceleration = last - prev = 0.0 (constant),
    # so is_accelerating = False → squeeze_risk False
    a = _make_analysis(_rate(rate=EXTREME_THRESHOLD * 2), h)
    assert a.extreme_streak == 3
    assert not a.is_squeeze_risk  # not accelerating


def test_squeeze_risk_true_when_rising_extreme():
    h = FundingHistory(window=168, ewma_span=8)
    h.push(EXTREME_THRESHOLD * 2, 0)
    h.push(EXTREME_THRESHOLD * 2 + ACCEL_THRESHOLD * 2, 1)
    # streak=2, acceleration > ACCEL_THRESHOLD → is_accelerating True
    a = _make_analysis(_rate(rate=EXTREME_THRESHOLD * 2 + ACCEL_THRESHOLD * 2), h)
    assert a.is_extreme is True
    assert a.is_accelerating is True
    assert a.extreme_streak >= 2
    assert a.is_squeeze_risk is True


# ── Carry metrics ─────────────────────────────────────────────────────────────

def test_make_analysis_annualized_carry():
    h = _history_with([0.0001] * 20)
    a = _make_analysis(_rate(), h)
    assert a.annualized_carry == pytest.approx(0.0001 * 1095)


def test_make_analysis_daily_carry():
    h = _history_with([0.0001] * 20)
    a = _make_analysis(_rate(), h)
    assert a.daily_carry == pytest.approx(0.0001 * 3)


# ── CI bounds ─────────────────────────────────────────────────────────────────

def test_make_analysis_ci_contains_mean():
    rates = [0.0001 * (1 + i % 5) for i in range(30)]
    h = _history_with(rates)
    a = _make_analysis(_rate(), h)
    assert a.ci_lower <= a.mean_rate <= a.ci_upper


# ── Regime ────────────────────────────────────────────────────────────────────

def test_make_analysis_regime_neutral():
    h = _history_with([0.00005] * 20)
    a = _make_analysis(_rate(rate=0.00005), h)
    assert a.regime == "neutral"


def test_make_analysis_regime_strongly_bullish():
    h = _history_with([EXTREME_THRESHOLD * 2] * 20)
    a = _make_analysis(_rate(rate=EXTREME_THRESHOLD * 2), h)
    assert a.regime == "strongly_bullish"


# ── Acceleration direction ────────────────────────────────────────────────────

def test_make_analysis_acceleration_direction_rising():
    h = _history_with([0.0001, 0.0001 + ACCEL_THRESHOLD * 2])
    a = _make_analysis(_rate(), h)
    assert a.acceleration_direction == "rising"
    assert a.is_accelerating is True


def test_make_analysis_acceleration_direction_stable():
    h = _history_with([0.0001, 0.0001, 0.0001])
    a = _make_analysis(_rate(), h)
    assert a.acceleration_direction == "stable"
    assert a.is_accelerating is False


# ── FundingEngine async integration ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_publishes_analysis():
    bus = MarketDataBus()
    engine = FundingEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)  # let consumer task reach await q.get()

    sub = bus.subscribe("funding_analysis.BYBIT.BTCUSDT")
    fr = FundingRate(
        exchange=Exchange.BYBIT,
        symbol="BTCUSDT",
        rate=0.0001,
        predicted=0.0001,
        next_funding_ts=1_000_000 + 8 * 3_600_000,
        ts_ms=1_000_000,
    )
    bus.publish("funding.BYBIT.BTCUSDT", fr)
    analysis = await asyncio.wait_for(sub.get(), timeout=1.0)

    assert isinstance(analysis, FundingAnalysis)
    assert analysis.symbol == "BTCUSDT"
    assert analysis.current_rate == pytest.approx(0.0001)

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_accumulates_history():
    bus = MarketDataBus()
    engine = FundingEngine(bus=bus, exchange="BYBIT")
    await engine.start(["ETHUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("funding_analysis.BYBIT.ETHUSDT")

    for i in range(5):
        fr = FundingRate(
            exchange=Exchange.BYBIT,
            symbol="ETHUSDT",
            rate=0.0001 * (i + 1),
            predicted=0.0001,
            next_funding_ts=(i + 1) * 8 * 3_600_000,
            ts_ms=i * 8 * 3_600_000,
        )
        bus.publish("funding.BYBIT.ETHUSDT", fr)
        await asyncio.sleep(0)

    # Drain all 5 analyses
    analyses = []
    for _ in range(5):
        a = await asyncio.wait_for(sub.get(), timeout=1.0)
        analyses.append(a)

    assert len(analyses) == 5
    # History grows: last analysis has count=5
    history = engine.get_history("ETHUSDT")
    assert history is not None
    assert history.count == 5

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_get_analysis_returns_latest():
    bus = MarketDataBus()
    engine = FundingEngine(bus=bus, exchange="BYBIT")
    await engine.start(["SOLUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("funding_analysis.BYBIT.SOLUSDT")

    fr = FundingRate(
        exchange=Exchange.BYBIT,
        symbol="SOLUSDT",
        rate=0.0002,
        predicted=0.0002,
        next_funding_ts=999 + 8 * 3_600_000,
        ts_ms=999,
    )
    bus.publish("funding.BYBIT.SOLUSDT", fr)
    await asyncio.wait_for(sub.get(), timeout=1.0)

    latest = engine.get_analysis("SOLUSDT")
    assert latest is not None
    assert latest.current_rate == pytest.approx(0.0002)

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_get_analysis_none_before_data():
    bus = MarketDataBus()
    engine = FundingEngine(bus=bus, exchange="BYBIT")
    await engine.start(["XRPUSDT"])

    assert engine.get_analysis("XRPUSDT") is None
    assert engine.get_history("XRPUSDT") is not None  # pre-created

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_multiple_symbols_independent():
    bus = MarketDataBus()
    engine = FundingEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT", "ETHUSDT"])
    await asyncio.sleep(0)

    sub_btc = bus.subscribe("funding_analysis.BYBIT.BTCUSDT")
    sub_eth = bus.subscribe("funding_analysis.BYBIT.ETHUSDT")

    bus.publish("funding.BYBIT.BTCUSDT", FundingRate(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        rate=0.0003, predicted=0.0003, next_funding_ts=8 * 3_600_000 + 1, ts_ms=1,
    ))
    bus.publish("funding.BYBIT.ETHUSDT", FundingRate(
        exchange=Exchange.BYBIT, symbol="ETHUSDT",
        rate=-0.0001, predicted=-0.0001, next_funding_ts=8 * 3_600_000 + 2, ts_ms=2,
    ))

    a_btc = await asyncio.wait_for(sub_btc.get(), timeout=1.0)
    a_eth = await asyncio.wait_for(sub_eth.get(), timeout=1.0)

    assert a_btc.symbol == "BTCUSDT"
    assert a_eth.symbol == "ETHUSDT"
    assert a_btc.current_rate != a_eth.current_rate

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_stop_cancels_tasks():
    bus = MarketDataBus()
    engine = FundingEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT"])
    await engine.stop()
    # After stop, internal task list is empty
    assert engine._tasks == []
