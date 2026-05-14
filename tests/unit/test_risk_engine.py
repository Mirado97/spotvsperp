from __future__ import annotations

import asyncio

import pytest

from src.core.bus import MarketDataBus
from src.funding.models import FundingAnalysis
from src.liquidation.models import CASCADE_THRESHOLD_USD, LiquidationAlert
from src.models.market import Exchange, InstrumentType, Ticker
from src.models.orders import Fill, OrderSide
from src.risk.engine import (
    RiskEngine,
    _check_delta,
    _check_drawdown,
    _check_exposure,
    _check_funding_streak,
    _check_liq,
)
from src.risk.models import RiskAlert, RiskLevel, RiskLimits


# ── Helpers ───────────────────────────────────────────────────────────────────

def _limits(**overrides) -> RiskLimits:
    lims = RiskLimits()
    for k, v in overrides.items():
        setattr(lims, k, v)
    return lims


def _fill(
    symbol: str = "BTCUSDT",
    side: OrderSide = OrderSide.BUY,
    qty: float = 0.01,
    price: float = 50_000.0,
    fee: float = 0.0,
    instrument_type: InstrumentType = InstrumentType.SPOT,
) -> Fill:
    return Fill(
        exchange=Exchange.BYBIT, symbol=symbol,
        order_id="o1", fill_id="f1",
        side=side, price=price, qty=qty,
        fee=fee, fee_currency="USDT", ts_ms=1,
        instrument_type=instrument_type,
    )


def _ticker(symbol: str = "BTCUSDT", mid: float = 50_000.0) -> Ticker:
    return Ticker(
        exchange=Exchange.BYBIT, symbol=symbol,
        instrument_type=InstrumentType.PERPETUAL,
        bid=mid - 10, ask=mid + 10, last=mid,
        volume_24h=1000.0, ts_ms=1,
    )


def _funding_analysis(symbol: str = "BTCUSDT", extreme_streak: int = 0) -> FundingAnalysis:
    return FundingAnalysis(
        exchange=Exchange.BYBIT, symbol=symbol,
        current_rate=0.0003, predicted_rate=0.0003, ewma_rate=0.0003,
        mean_rate=0.0003, std_rate=0.0001, z_score=1.0, percentile=0.9,
        predicted_next=0.0003, ci_lower=0.0002, ci_upper=0.0004,
        regime="strongly_bullish",
        acceleration=0.0, is_accelerating=False, acceleration_direction="stable",
        is_extreme=True, rate_direction="longs_paying", extreme_streak=extreme_streak,
        annualized_carry=0.33, daily_carry=0.0009, ts_ms=1,
    )


def _liq_alert(
    symbol: str = "BTCUSDT",
    net_pressure: float = 0.0,
    is_cascade: bool = False,
    liq_rate: float = 0.0,
) -> LiquidationAlert:
    return LiquidationAlert(
        exchange=Exchange.BYBIT, symbol=symbol,
        window_ms=300_000,
        long_liq_usd=0.0, short_liq_usd=0.0, total_liq_usd=0.0,
        net_pressure=net_pressure,
        squeeze_side="neutral",
        is_cascade=is_cascade,
        liq_rate_per_min=liq_rate,
        event_count=0,
        oi_value=0.0, oi_change_pct=0.0, is_oi_spike=False,
        ts_ms=1,
    )


# ── Pure check functions ──────────────────────────────────────────────────────

def test_check_delta_ok():
    lims = _limits(max_delta_usd=5_000.0)
    assert _check_delta(Exchange.BYBIT, "BTCUSDT", 1_000.0, lims, 0) is None


def test_check_delta_warning_at_80pct():
    lims = _limits(max_delta_usd=5_000.0)
    alert = _check_delta(Exchange.BYBIT, "BTCUSDT", 4_100.0, lims, 0)
    assert alert is not None
    assert alert.risk_level == RiskLevel.WARNING


def test_check_delta_critical_at_limit():
    lims = _limits(max_delta_usd=5_000.0)
    alert = _check_delta(Exchange.BYBIT, "BTCUSDT", 5_000.0, lims, 0)
    assert alert is not None
    assert alert.risk_level == RiskLevel.CRITICAL


def test_check_delta_negative_delta():
    lims = _limits(max_delta_usd=5_000.0)
    alert = _check_delta(Exchange.BYBIT, "BTCUSDT", -5_500.0, lims, 0)
    assert alert is not None
    assert alert.risk_level == RiskLevel.CRITICAL


def test_check_exposure_ok():
    lims = _limits(max_total_exposure_usd=200_000.0)
    assert _check_exposure(Exchange.BYBIT, 100_000.0, lims, 0) is None


def test_check_exposure_warning():
    lims = _limits(max_total_exposure_usd=200_000.0)
    alert = _check_exposure(Exchange.BYBIT, 165_000.0, lims, 0)
    assert alert is not None
    assert alert.risk_level == RiskLevel.WARNING


def test_check_drawdown_ok():
    lims = _limits(max_drawdown_pct=0.05)
    assert _check_drawdown(Exchange.BYBIT, 0.01, lims, 0) is None


def test_check_drawdown_warning_at_50pct():
    lims = _limits(max_drawdown_pct=0.10)
    alert = _check_drawdown(Exchange.BYBIT, 0.06, lims, 0)
    assert alert is not None
    assert alert.risk_level == RiskLevel.WARNING


def test_check_drawdown_emergency_at_limit():
    lims = _limits(max_drawdown_pct=0.05)
    alert = _check_drawdown(Exchange.BYBIT, 0.05, lims, 0)
    assert alert is not None
    assert alert.risk_level == RiskLevel.EMERGENCY
    assert alert.is_emergency


def test_check_funding_streak_ok():
    lims = _limits(funding_extreme_streak_limit=6)
    assert _check_funding_streak(_funding_analysis(extreme_streak=3), lims, Exchange.BYBIT) is None


def test_check_funding_streak_warning():
    lims = _limits(funding_extreme_streak_limit=6)
    alert = _check_funding_streak(_funding_analysis(extreme_streak=6), lims, Exchange.BYBIT)
    assert alert is not None
    assert alert.risk_level == RiskLevel.WARNING
    assert alert.reason == "extreme_funding_streak"


def test_check_liq_ok():
    lims = _limits(liq_pressure_threshold=0.8)
    assert _check_liq(_liq_alert(net_pressure=0.5), lims, Exchange.BYBIT) is None


def test_check_liq_squeeze_warning():
    lims = _limits(liq_pressure_threshold=0.8)
    alert = _check_liq(_liq_alert(net_pressure=0.85), lims, Exchange.BYBIT)
    assert alert is not None
    assert alert.risk_level == RiskLevel.WARNING
    assert alert.reason == "liq_squeeze"


def test_check_liq_cascade_critical():
    lims = _limits()
    alert = _check_liq(_liq_alert(is_cascade=True, liq_rate=CASCADE_THRESHOLD_USD * 2), lims, Exchange.BYBIT)
    assert alert is not None
    assert alert.risk_level == RiskLevel.CRITICAL
    assert alert.reason == "liq_cascade"


# ── RiskEngine: async integration ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_publishes_delta_alert_on_fill():
    bus = MarketDataBus()
    limits = _limits(max_delta_usd=1_000.0)
    engine = RiskEngine(bus=bus, limits=limits, initial_equity=100_000.0)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub_alert = bus.subscribe("risk_alert.BYBIT")
    sub_tick = bus.subscribe("ticker.BYBIT.BTCUSDT.PERP")

    # Provide mark price first
    bus.publish("ticker.BYBIT.BTCUSDT.PERP", _ticker(mid=50_000.0))
    await asyncio.sleep(0)

    # Fill that creates large delta: 0.1 BTC spot only, perp not hedged → delta = 5_000 USD > limit
    bus.publish("fill.BYBIT.BTCUSDT", _fill(
        side=OrderSide.BUY, qty=0.1,
        instrument_type=InstrumentType.SPOT,
    ))
    await asyncio.sleep(0)

    alert = await asyncio.wait_for(sub_alert.get(), timeout=1.0)
    assert isinstance(alert, RiskAlert)
    assert alert.reason == "delta_exceeded"
    assert alert.risk_level >= RiskLevel.CRITICAL

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_emergency_on_drawdown():
    bus = MarketDataBus()
    # small initial equity so fees trigger drawdown
    limits = _limits(max_drawdown_pct=0.01)
    engine = RiskEngine(bus=bus, limits=limits, initial_equity=1_000.0)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub_alert = bus.subscribe("risk_alert.BYBIT")
    sub_emergency = bus.subscribe("emergency_stop.BYBIT")

    # Fee of 10 USDT on 1000 equity = 1% drawdown → EMERGENCY
    bus.publish("fill.BYBIT.BTCUSDT", _fill(fee=10.0, instrument_type=InstrumentType.SPOT))
    await asyncio.sleep(0)

    alert = await asyncio.wait_for(sub_alert.get(), timeout=1.0)
    assert alert.is_emergency
    assert engine.is_emergency

    emergency = await asyncio.wait_for(sub_emergency.get(), timeout=1.0)
    assert emergency.is_emergency

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_reset_emergency():
    bus = MarketDataBus()
    limits = _limits(max_drawdown_pct=0.01)
    engine = RiskEngine(bus=bus, limits=limits, initial_equity=1_000.0)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("risk_alert.BYBIT")
    bus.publish("fill.BYBIT.BTCUSDT", _fill(fee=10.0, instrument_type=InstrumentType.SPOT))
    await asyncio.wait_for(sub.get(), timeout=1.0)

    assert engine.is_emergency
    engine.reset_emergency()
    assert not engine.is_emergency

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_extreme_funding_alert():
    bus = MarketDataBus()
    limits = _limits(funding_extreme_streak_limit=3)
    engine = RiskEngine(bus=bus, limits=limits, initial_equity=100_000.0)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("risk_alert.BYBIT")
    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding_analysis(extreme_streak=3))
    await asyncio.sleep(0)

    alert = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert alert.reason == "extreme_funding_streak"
    assert alert.risk_level == RiskLevel.WARNING

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_liq_cascade_alert():
    bus = MarketDataBus()
    limits = _limits()
    engine = RiskEngine(bus=bus, limits=limits, initial_equity=100_000.0)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("risk_alert.BYBIT")
    bus.publish("liq_alert.BYBIT.BTCUSDT", _liq_alert(
        is_cascade=True, liq_rate=CASCADE_THRESHOLD_USD * 2,
    ))
    await asyncio.sleep(0)

    alert = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert alert.reason == "liq_cascade"
    assert alert.risk_level == RiskLevel.CRITICAL

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_snapshot():
    bus = MarketDataBus()
    limits = _limits()
    engine = RiskEngine(bus=bus, limits=limits, initial_equity=100_000.0)
    await engine.start(["BTCUSDT"])

    snap = engine.snapshot()
    assert snap.total_exposure_usd == 0.0
    assert not snap.is_emergency
    assert snap.risk_level == int(RiskLevel.OK)

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_stop_clears_tasks():
    bus = MarketDataBus()
    engine = RiskEngine(bus=bus, limits=_limits(), initial_equity=100_000.0)
    await engine.start(["BTCUSDT"])
    await engine.stop()
    assert engine._tasks == []
