from __future__ import annotations

import pytest

from src.exchange.bybit.parsers import parse_linear_ticker, parse_spot_ticker
from src.models.market import Exchange, InstrumentType

# ── Fixture messages (representative Bybit V5 snapshots) ─────────────────────

_SPOT_MSG = {
    "topic": "tickers.BTCUSDT",
    "ts": 1673853746003,
    "type": "snapshot",
    "data": {
        "symbol": "BTCUSDT",
        "lastPrice": "21109.77",
        "highPrice24h": "21426.99",
        "lowPrice24h": "20575.00",
        "volume24h": "6780.866843",
        "bid1Price": "21109.00",
        "ask1Price": "21110.00",
    },
}

_LINEAR_MSG = {
    "topic": "tickers.BTCUSDT",
    "ts": 1673853746003,
    "type": "snapshot",
    "data": {
        "symbol": "BTCUSDT",
        "lastPrice": "21100.00",
        "bid1Price": "21099.50",
        "ask1Price": "21100.50",
        "volume24h": "16765.215",
        "openInterest": "373504.631",
        "openInterestValue": "6202890.08",
        "nextFundingTime": "1673884800000",
        "fundingRate": "-0.000212",
        "predictedFundingRate": "-0.000200",
    },
}

_TS = 1673853746003


# ── Spot ticker ───────────────────────────────────────────────────────────────

def test_spot_ticker_basic_fields():
    t = parse_spot_ticker(_SPOT_MSG, _TS)
    assert t is not None
    assert t.exchange == Exchange.BYBIT
    assert t.symbol == "BTCUSDT"
    assert t.instrument_type == InstrumentType.SPOT
    assert t.bid == 21109.00
    assert t.ask == 21110.00
    assert t.last == 21109.77
    assert t.volume_24h == pytest.approx(6780.866843)
    assert t.ts_ms == _TS


def test_spot_ticker_fallback_to_last_when_no_bid_ask():
    msg = {
        "topic": "tickers.ETHUSDT",
        "ts": 100,
        "data": {"symbol": "ETHUSDT", "lastPrice": "3000.00", "volume24h": "1000"},
    }
    t = parse_spot_ticker(msg, 100)
    assert t is not None
    assert t.bid == 3000.00
    assert t.ask == 3000.00


def test_spot_ticker_returns_none_on_missing_symbol():
    t = parse_spot_ticker({"topic": "tickers.X", "ts": 0, "data": {}}, 0)
    assert t is None


def test_spot_ticker_returns_none_on_missing_data_key():
    t = parse_spot_ticker({"topic": "tickers.X", "ts": 0}, 0)
    assert t is None


# ── Linear ticker ─────────────────────────────────────────────────────────────

def test_linear_ticker_basic_fields():
    ticker, funding, oi = parse_linear_ticker(_LINEAR_MSG, _TS)

    assert ticker is not None
    assert ticker.instrument_type == InstrumentType.PERPETUAL
    assert ticker.bid == 21099.50
    assert ticker.ask == 21100.50
    assert ticker.last == 21100.00


def test_linear_ticker_funding_fields():
    _, funding, _ = parse_linear_ticker(_LINEAR_MSG, _TS)
    assert funding is not None
    assert funding.rate == pytest.approx(-0.000212)
    assert funding.predicted == pytest.approx(-0.000200)
    assert funding.next_funding_ts == 1673884800000
    assert funding.interval_h == 8
    assert funding.is_extreme is False


def test_linear_ticker_oi_fields():
    _, _, oi = parse_linear_ticker(_LINEAR_MSG, _TS)
    assert oi is not None
    assert oi.oi == pytest.approx(373504.631)
    assert oi.oi_value == pytest.approx(6202890.08)


def test_linear_ticker_extreme_funding():
    msg = {**_LINEAR_MSG, "data": {**_LINEAR_MSG["data"], "fundingRate": "0.0015"}}
    _, funding, _ = parse_linear_ticker(msg, _TS)
    assert funding is not None
    assert funding.is_extreme is True


def test_linear_ticker_no_funding_when_absent():
    data = {k: v for k, v in _LINEAR_MSG["data"].items()
            if k not in ("fundingRate", "nextFundingTime")}
    msg = {**_LINEAR_MSG, "data": data}
    _, funding, _ = parse_linear_ticker(msg, _TS)
    assert funding is None


def test_linear_ticker_no_oi_when_absent():
    data = {k: v for k, v in _LINEAR_MSG["data"].items() if k != "openInterest"}
    msg = {**_LINEAR_MSG, "data": data}
    _, _, oi = parse_linear_ticker(msg, _TS)
    assert oi is None


def test_linear_ticker_returns_none_tuple_on_malformed():
    ticker, funding, oi = parse_linear_ticker({"topic": "tickers.X", "ts": 0, "data": {}}, 0)
    assert ticker is None
    assert funding is None
    assert oi is None


# ── Funding rate computed properties ─────────────────────────────────────────

def test_funding_annualized_and_daily():
    _, funding, _ = parse_linear_ticker(_LINEAR_MSG, _TS)
    assert funding is not None
    # -0.000212 * 1095 ≈ -0.23214
    assert funding.annualized == pytest.approx(-0.000212 * 1095, rel=1e-6)
    # -0.000212 * 3 ≈ -0.000636
    assert funding.daily == pytest.approx(-0.000212 * 3, rel=1e-6)
