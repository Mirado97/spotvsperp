from __future__ import annotations

from enum import IntEnum

import msgspec


class Exchange(IntEnum):
    BYBIT = 1
    BINANCE = 2
    OKX = 3
    BITGET = 4
    GATE = 5
    MEXC = 6


class InstrumentType(IntEnum):
    SPOT = 1
    PERPETUAL = 2
    FUTURES = 3


class Ticker(msgspec.Struct, frozen=True, gc=False):
    exchange: Exchange
    symbol: str
    instrument_type: InstrumentType
    bid: float
    ask: float
    last: float
    volume_24h: float
    ts_ms: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0

    @property
    def spread(self) -> float:
        return self.ask - self.bid

    @property
    def spread_bps(self) -> float:
        return self.spread / self.mid * 10_000


class OrderBookLevel(msgspec.Struct, frozen=True, gc=False):
    price: float
    qty: float


class OrderBook(msgspec.Struct, frozen=True):
    exchange: Exchange
    symbol: str
    instrument_type: InstrumentType
    bids: list[OrderBookLevel]
    asks: list[OrderBookLevel]
    ts_ms: int
    seq: int = 0

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    def imbalance(self, depth: int = 5) -> float:
        """Orderbook imbalance in [-1, 1]. Positive = bid-heavy."""
        bid_qty = sum(lvl.qty for lvl in self.bids[:depth])
        ask_qty = sum(lvl.qty for lvl in self.asks[:depth])
        total = bid_qty + ask_qty
        if total == 0:
            return 0.0
        return (bid_qty - ask_qty) / total


class Trade(msgspec.Struct, frozen=True, gc=False):
    exchange: Exchange
    symbol: str
    instrument_type: InstrumentType
    price: float
    qty: float
    side: str  # "Buy" | "Sell"
    ts_ms: int


class OpenInterest(msgspec.Struct, frozen=True, gc=False):
    exchange: Exchange
    symbol: str
    oi: float        # base currency
    oi_value: float  # USD notional
    ts_ms: int
