from __future__ import annotations

import msgspec
import pytest

from src.models.funding import FundingRate, FundingSnapshot
from src.models.market import Exchange, InstrumentType, OrderBook, OrderBookLevel, Ticker
from src.models.orders import Fill, Order, OrderSide, OrderStatus, OrderType
from src.models.positions import HedgePosition, Position, PositionSide


# ── Ticker ────────────────────────────────────────────────────────────────────

def test_ticker_mid_and_spread():
    t = Ticker(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        instrument_type=InstrumentType.SPOT,
        bid=100_000.0, ask=100_002.0, last=100_001.0,
        volume_24h=1234.56, ts_ms=1_700_000_000_000,
    )
    assert t.mid == 100_001.0
    assert t.spread == 2.0
    assert t.spread_bps == pytest.approx(0.2, rel=1e-3)


def test_ticker_is_frozen():
    t = Ticker(
        exchange=Exchange.BYBIT, symbol="ETHUSDT",
        instrument_type=InstrumentType.PERPETUAL,
        bid=3000.0, ask=3001.0, last=3000.5,
        volume_24h=50_000.0, ts_ms=1_700_000_000_000,
    )
    with pytest.raises(AttributeError):
        t.bid = 2999.0  # type: ignore[misc]


# ── OrderBook ─────────────────────────────────────────────────────────────────

def test_orderbook_imbalance_bid_heavy():
    bids = [OrderBookLevel(100.0, 10.0), OrderBookLevel(99.0, 5.0)]
    asks = [OrderBookLevel(101.0, 3.0), OrderBookLevel(102.0, 2.0)]
    ob = OrderBook(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        instrument_type=InstrumentType.SPOT,
        bids=bids, asks=asks, ts_ms=0,
    )
    imb = ob.imbalance(depth=2)
    # bid_qty=15, ask_qty=5, total=20 → (15-5)/20 = 0.5
    assert abs(imb - 0.5) < 1e-9


def test_orderbook_imbalance_empty():
    ob = OrderBook(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        instrument_type=InstrumentType.SPOT,
        bids=[], asks=[], ts_ms=0,
    )
    assert ob.imbalance() == 0.0


# ── FundingRate ───────────────────────────────────────────────────────────────

def test_funding_rate_annualized():
    fr = FundingRate(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        rate=0.0001, predicted=0.00012,
        next_funding_ts=1_700_000_000_000,
        interval_h=8, ts_ms=0,
    )
    # 0.0001 * (365*24/8) = 0.0001 * 1095 = 0.1095
    assert abs(fr.annualized - 0.1095) < 1e-9
    # 0.0001 * 3 = 0.0003
    assert abs(fr.daily - 0.0003) < 1e-9


def test_funding_rate_extreme_detection():
    normal = FundingRate(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        rate=0.0001, predicted=0.0, next_funding_ts=0,
    )
    extreme = FundingRate(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        rate=0.0005, predicted=0.0, next_funding_ts=0,
    )
    assert not normal.is_extreme
    assert extreme.is_extreme


def test_funding_snapshot_regime():
    snap = FundingSnapshot(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        rates=[0.0004, 0.0005, 0.0003],
        avg_rate=0.0004, std_rate=0.0001,
        min_rate=0.0003, max_rate=0.0005,
        ts_ms=0,
    )
    assert snap.regime == "strongly_long"


# ── Order ─────────────────────────────────────────────────────────────────────

def test_order_remaining_qty():
    o = Order(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        order_id="123", client_order_id="c123",
        side=OrderSide.BUY, order_type=OrderType.LIMIT,
        qty=1.0, price=100_000.0,
        status=OrderStatus.PARTIALLY_FILLED,
        filled_qty=0.3,
    )
    assert abs(o.remaining_qty - 0.7) < 1e-9
    assert o.is_active
    assert not o.is_terminal


def test_order_terminal_statuses():
    for status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED):
        o = Order(
            exchange=Exchange.BYBIT, symbol="BTCUSDT",
            order_id="x", client_order_id="cx",
            side=OrderSide.SELL, order_type=OrderType.MARKET,
            qty=1.0, price=0.0, status=status,
        )
        assert o.is_terminal
        assert not o.is_active


# ── HedgePosition ─────────────────────────────────────────────────────────────

def test_hedge_position_delta_neutral():
    spot = Position(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        side=PositionSide.LONG, size=1.0,
        entry_price=100_000.0, mark_price=100_000.0,
        unrealized_pnl=0.0,
    )
    perp = Position(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        side=PositionSide.SHORT, size=1.0,
        entry_price=100_100.0, mark_price=100_100.0,
        unrealized_pnl=0.0,
    )
    hedge = HedgePosition(symbol="BTCUSDT", spot=spot, perp=perp, strategy_id="s1")
    assert hedge.is_delta_neutral
    assert abs(hedge.net_delta) < 0.001


def test_hedge_position_not_delta_neutral():
    spot = Position(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        side=PositionSide.LONG, size=1.0,
        entry_price=100_000.0, mark_price=100_000.0,
        unrealized_pnl=0.0,
    )
    perp = Position(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        side=PositionSide.SHORT, size=0.5,  # under-hedged
        entry_price=100_100.0, mark_price=100_100.0,
        unrealized_pnl=0.0,
    )
    hedge = HedgePosition(symbol="BTCUSDT", spot=spot, perp=perp, strategy_id="s2")
    assert not hedge.is_delta_neutral
    assert abs(hedge.net_delta - 0.5) < 1e-9


# ── msgspec serialization ─────────────────────────────────────────────────────

def test_msgspec_encode_decode_ticker():
    t = Ticker(
        exchange=Exchange.BYBIT, symbol="ETHUSDT",
        instrument_type=InstrumentType.PERPETUAL,
        bid=3000.0, ask=3001.0, last=3000.5,
        volume_24h=50_000.0, ts_ms=1_700_000_000_000,
    )
    encoded = msgspec.json.encode(t)
    decoded = msgspec.json.decode(encoded, type=Ticker)
    assert decoded.symbol == t.symbol
    assert decoded.bid == t.bid
    assert decoded.exchange == Exchange.BYBIT


def test_msgspec_encode_decode_funding():
    fr = FundingRate(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        rate=0.0001, predicted=0.00012,
        next_funding_ts=1_700_000_028_000,
        interval_h=8, ts_ms=1_700_000_000_000,
    )
    encoded = msgspec.json.encode(fr)
    decoded = msgspec.json.decode(encoded, type=FundingRate)
    assert decoded.rate == fr.rate
    assert abs(decoded.annualized - fr.annualized) < 1e-12
