from __future__ import annotations

import pytest

from src.models.market import Exchange, InstrumentType
from src.models.orders import Fill, OrderSide
from src.risk.delta_tracker import DeltaTracker


def _fill(
    symbol: str = "BTCUSDT",
    side: OrderSide = OrderSide.BUY,
    qty: float = 0.01,
    price: float = 50_000.0,
    instrument_type: InstrumentType = InstrumentType.SPOT,
    fee: float = 0.0,
) -> Fill:
    return Fill(
        exchange=Exchange.BYBIT,
        symbol=symbol,
        order_id="o1",
        fill_id="f1",
        side=side,
        price=price,
        qty=qty,
        fee=fee,
        fee_currency="USDT",
        ts_ms=0,
        instrument_type=instrument_type,
    )


# ── Empty state ───────────────────────────────────────────────────────────────

def test_empty_delta_zero():
    t = DeltaTracker()
    assert t.net_delta("BTCUSDT") == 0.0
    assert t.net_delta_usd("BTCUSDT") == 0.0
    assert t.total_exposure_usd() == 0.0
    assert t.max_delta_usd_symbol() == ("", 0.0)


# ── Spot fills ────────────────────────────────────────────────────────────────

def test_spot_buy_increases_spot_qty():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY, qty=0.1, instrument_type=InstrumentType.SPOT))
    assert t.position("BTCUSDT").spot_qty == pytest.approx(0.1)
    assert t.position("BTCUSDT").perp_qty == pytest.approx(0.0)


def test_spot_sell_decreases_spot_qty():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY, qty=0.2, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(side=OrderSide.SELL, qty=0.1, instrument_type=InstrumentType.SPOT))
    assert t.position("BTCUSDT").spot_qty == pytest.approx(0.1)


def test_spot_avg_price_tracking():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY, qty=1.0, price=50_000.0, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(side=OrderSide.BUY, qty=1.0, price=52_000.0, instrument_type=InstrumentType.SPOT))
    assert t.position("BTCUSDT").spot_avg_price == pytest.approx(51_000.0)


# ── Perp fills ────────────────────────────────────────────────────────────────

def test_perp_sell_decreases_perp_qty():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.SELL, qty=0.1, instrument_type=InstrumentType.PERPETUAL))
    assert t.position("BTCUSDT").perp_qty == pytest.approx(-0.1)


def test_perp_buy_closes_short():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.SELL, qty=0.1, instrument_type=InstrumentType.PERPETUAL))
    t.on_fill(_fill(side=OrderSide.BUY, qty=0.05, instrument_type=InstrumentType.PERPETUAL))
    assert t.position("BTCUSDT").perp_qty == pytest.approx(-0.05)


# ── Net delta ─────────────────────────────────────────────────────────────────

def test_net_delta_neutral_carry():
    t = DeltaTracker()
    # Long 0.1 BTC spot, short 0.1 BTC perp → net_delta = 0
    t.on_fill(_fill(side=OrderSide.BUY,  qty=0.1, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(side=OrderSide.SELL, qty=0.1, instrument_type=InstrumentType.PERPETUAL))
    assert t.net_delta("BTCUSDT") == pytest.approx(0.0, abs=1e-9)


def test_net_delta_nonzero_after_partial_hedge():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY,  qty=0.1, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(side=OrderSide.SELL, qty=0.08, instrument_type=InstrumentType.PERPETUAL))
    assert t.net_delta("BTCUSDT") == pytest.approx(0.02)


def test_net_delta_usd_uses_mark_price():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY,  qty=0.1, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(side=OrderSide.SELL, qty=0.05, instrument_type=InstrumentType.PERPETUAL))
    t.on_price("BTCUSDT", 50_000.0)
    assert t.net_delta_usd("BTCUSDT") == pytest.approx(0.05 * 50_000.0)


def test_net_delta_usd_zero_without_price():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY, qty=0.1, instrument_type=InstrumentType.SPOT))
    # No price set → 0 delta usd
    assert t.net_delta_usd("BTCUSDT") == 0.0


# ── Exposure ──────────────────────────────────────────────────────────────────

def test_exposure_delta_neutral_carry():
    t = DeltaTracker()
    t.on_fill(_fill(side=OrderSide.BUY,  qty=1.0, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(side=OrderSide.SELL, qty=1.0, instrument_type=InstrumentType.PERPETUAL))
    t.on_price("BTCUSDT", 50_000.0)
    # (|1.0| + |-1.0|) / 2 * 50_000 = 50_000
    assert t.total_exposure_usd() == pytest.approx(50_000.0)


def test_exposure_multiple_symbols():
    t = DeltaTracker()
    t.on_fill(_fill(symbol="BTCUSDT", side=OrderSide.BUY, qty=1.0, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(symbol="BTCUSDT", side=OrderSide.SELL, qty=1.0, instrument_type=InstrumentType.PERPETUAL))
    t.on_price("BTCUSDT", 50_000.0)

    t.on_fill(_fill(symbol="ETHUSDT", side=OrderSide.BUY, qty=10.0, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(symbol="ETHUSDT", side=OrderSide.SELL, qty=10.0, instrument_type=InstrumentType.PERPETUAL))
    t.on_price("ETHUSDT", 3_000.0)

    # BTC: 50_000 + ETH: (|10|+|10|)/2 * 3000 = 30_000
    assert t.total_exposure_usd() == pytest.approx(50_000.0 + 30_000.0)


# ── max_delta_usd_symbol ──────────────────────────────────────────────────────

def test_max_delta_usd_symbol_finds_worst():
    t = DeltaTracker()
    # BTCUSDT: imbalanced
    t.on_fill(_fill(symbol="BTCUSDT", side=OrderSide.BUY, qty=1.0, instrument_type=InstrumentType.SPOT))
    t.on_price("BTCUSDT", 50_000.0)
    # ETHUSDT: balanced
    t.on_fill(_fill(symbol="ETHUSDT", side=OrderSide.BUY,  qty=1.0, instrument_type=InstrumentType.SPOT))
    t.on_fill(_fill(symbol="ETHUSDT", side=OrderSide.SELL, qty=1.0, instrument_type=InstrumentType.PERPETUAL))
    t.on_price("ETHUSDT", 3_000.0)

    sym, delta = t.max_delta_usd_symbol()
    assert sym == "BTCUSDT"
    assert delta == pytest.approx(50_000.0)
