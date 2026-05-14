from __future__ import annotations

import asyncio

import pytest

from src.core.bus import MarketDataBus
from src.exchange.bybit.parsers import parse_liquidation
from src.liquidation.engine import LiquidationEngine, _make_alert
from src.liquidation.history import LiquidationHistory, OIHistory
from src.liquidation.models import CASCADE_THRESHOLD_USD, LiquidationAlert
from src.models.liquidation import LiquidationEvent
from src.models.market import Exchange, OpenInterest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ev(
    side: str = "long",
    value_usd: float = 10_000.0,
    ts_ms: int = 0,
    symbol: str = "BTCUSDT",
) -> LiquidationEvent:
    price = 50_000.0
    return LiquidationEvent(
        exchange=Exchange.BYBIT,
        symbol=symbol,
        side=side,
        qty=value_usd / price,
        price=price,
        value_usd=value_usd,
        ts_ms=ts_ms,
    )


def _oi(value: float = 1_000_000.0, symbol: str = "BTCUSDT") -> OpenInterest:
    return OpenInterest(
        exchange=Exchange.BYBIT,
        symbol=symbol,
        oi=value / 50_000.0,
        oi_value=value,
        ts_ms=0,
    )


# ── parse_liquidation ─────────────────────────────────────────────────────────

def test_parse_liquidation_long():
    raw = {
        "topic": "liquidation.BTCUSDT",
        "ts": 1_000_000,
        "data": {"symbol": "BTCUSDT", "side": "Buy", "size": "0.01", "price": "50000"},
    }
    event = parse_liquidation(raw, 1_000_000)
    assert event is not None
    assert event.side == "long"
    assert event.qty == pytest.approx(0.01)
    assert event.price == pytest.approx(50_000.0)
    assert event.value_usd == pytest.approx(500.0)
    assert event.ts_ms == 1_000_000


def test_parse_liquidation_short():
    raw = {
        "topic": "liquidation.ETHUSDT",
        "ts": 2_000_000,
        "data": {"symbol": "ETHUSDT", "side": "Sell", "size": "1.0", "price": "3000"},
    }
    event = parse_liquidation(raw, 2_000_000)
    assert event is not None
    assert event.side == "short"
    assert event.value_usd == pytest.approx(3000.0)


def test_parse_liquidation_missing_field_returns_none():
    raw = {"topic": "liquidation.BTCUSDT", "ts": 0, "data": {"symbol": "BTCUSDT"}}
    assert parse_liquidation(raw, 0) is None


def test_parse_liquidation_missing_data_returns_none():
    raw = {"topic": "liquidation.BTCUSDT", "ts": 0}
    assert parse_liquidation(raw, 0) is None


# ── _make_alert: pure function ────────────────────────────────────────────────

def test_make_alert_empty_histories():
    liq = LiquidationHistory()
    oi = OIHistory()
    alert = _make_alert(Exchange.BYBIT, "BTCUSDT", liq, oi, ts_ms=0)
    assert isinstance(alert, LiquidationAlert)
    assert alert.total_liq_usd == 0.0
    assert alert.net_pressure == 0.0
    assert alert.squeeze_side == "neutral"
    assert not alert.is_cascade
    assert not alert.is_oi_spike
    assert alert.oi_value == 0.0


def test_make_alert_long_squeeze():
    liq = LiquidationHistory()
    liq.push(_ev(side="long", value_usd=1_000_000))
    liq.push(_ev(side="short", value_usd=1_000))
    alert = _make_alert(Exchange.BYBIT, "BTCUSDT", liq, OIHistory(), ts_ms=1)
    assert alert.squeeze_side == "long_squeeze"
    assert alert.is_long_squeeze is True
    assert alert.is_short_squeeze is False


def test_make_alert_cascade():
    liq = LiquidationHistory(window_ms=60_000)
    liq.push(_ev(side="long", value_usd=CASCADE_THRESHOLD_USD * 2, ts_ms=0))
    alert = _make_alert(Exchange.BYBIT, "BTCUSDT", liq, OIHistory(), ts_ms=0)
    assert alert.is_cascade is True
    assert alert.is_significant is True


def test_make_alert_oi_spike():
    oi = OIHistory(window=5)
    for _ in range(4):
        oi.push(1_000_000.0)
    oi.push(1_200_000.0)  # 20% spike
    alert = _make_alert(Exchange.BYBIT, "BTCUSDT", LiquidationHistory(), oi, ts_ms=0)
    assert alert.is_oi_spike is True
    assert alert.is_significant is True


def test_make_alert_not_significant():
    alert = _make_alert(Exchange.BYBIT, "BTCUSDT", LiquidationHistory(), OIHistory(), ts_ms=0)
    assert not alert.is_significant


# ── LiquidationEngine: async integration ─────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_publishes_alert():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("liq_alert.BYBIT.BTCUSDT")
    bus.publish("liquidation.BYBIT.BTCUSDT", _ev(side="long", value_usd=50_000))

    alert = await asyncio.wait_for(sub.get(), timeout=1.0)
    assert isinstance(alert, LiquidationAlert)
    assert alert.symbol == "BTCUSDT"
    assert alert.total_liq_usd == pytest.approx(50_000.0)
    assert alert.event_count == 1

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_accumulates_events():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT", window_ms=60_000)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("liq_alert.BYBIT.BTCUSDT")
    for i in range(3):
        bus.publish("liquidation.BYBIT.BTCUSDT", _ev(side="long", value_usd=10_000, ts_ms=i * 1000))
        await asyncio.sleep(0)

    alerts = []
    for _ in range(3):
        a = await asyncio.wait_for(sub.get(), timeout=1.0)
        alerts.append(a)

    assert alerts[-1].event_count == 3
    assert alerts[-1].total_liq_usd == pytest.approx(30_000.0)

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_oi_updates_history():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT", oi_window=5)
    await engine.start(["BTCUSDT"])
    await asyncio.sleep(0)

    # Push OI data
    for _ in range(4):
        bus.publish("oi.BYBIT.BTCUSDT", _oi(value=1_000_000.0))
    await asyncio.sleep(0)

    bus.publish("oi.BYBIT.BTCUSDT", _oi(value=1_200_000.0))
    await asyncio.sleep(0)

    oi_hist = engine.get_oi_history("BTCUSDT")
    assert oi_hist is not None
    # After at least one OI push processed:
    assert oi_hist.latest > 0.0

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_get_alert_none_before_events():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT")
    await engine.start(["ETHUSDT"])
    assert engine.get_alert("ETHUSDT") is None
    await engine.stop()


@pytest.mark.asyncio
async def test_engine_get_alert_after_event():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT")
    await engine.start(["SOLUSDT"])
    await asyncio.sleep(0)

    sub = bus.subscribe("liq_alert.BYBIT.SOLUSDT")
    bus.publish("liquidation.BYBIT.SOLUSDT", _ev(symbol="SOLUSDT", side="short", value_usd=5_000))
    await asyncio.wait_for(sub.get(), timeout=1.0)

    alert = engine.get_alert("SOLUSDT")
    assert alert is not None
    assert alert.short_liq_usd == pytest.approx(5_000.0)

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_multiple_symbols_independent():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT", "ETHUSDT"])
    await asyncio.sleep(0)

    sub_btc = bus.subscribe("liq_alert.BYBIT.BTCUSDT")
    sub_eth = bus.subscribe("liq_alert.BYBIT.ETHUSDT")

    bus.publish("liquidation.BYBIT.BTCUSDT", _ev(symbol="BTCUSDT", side="long", value_usd=100_000))
    bus.publish("liquidation.BYBIT.ETHUSDT", _ev(symbol="ETHUSDT", side="short", value_usd=50_000))

    a_btc = await asyncio.wait_for(sub_btc.get(), timeout=1.0)
    a_eth = await asyncio.wait_for(sub_eth.get(), timeout=1.0)

    assert a_btc.symbol == "BTCUSDT"
    assert a_eth.symbol == "ETHUSDT"
    assert a_btc.total_liq_usd != a_eth.total_liq_usd

    await engine.stop()


@pytest.mark.asyncio
async def test_engine_stop_clears_tasks():
    bus = MarketDataBus()
    engine = LiquidationEngine(bus=bus, exchange="BYBIT")
    await engine.start(["BTCUSDT"])
    await engine.stop()
    assert engine._tasks == []
