from __future__ import annotations

import time
import zlib
from dataclasses import dataclass

from src.models.market import Exchange, InstrumentType, OrderBook, OrderBookLevel


@dataclass(slots=True)
class BookSummary:
    """Lightweight snapshot consumed by the Basis Engine (Phase 4)."""
    exchange: Exchange
    symbol: str
    instrument_type: InstrumentType
    best_bid: float
    best_ask: float
    mid: float
    spread_bps: float
    imbalance_5: float   # top-5-level bid-ask imbalance in [-1, 1]
    ts_ms: int
    is_stale: bool


class OrderBookState:
    """
    Mutable in-memory orderbook state machine.

    Prices and quantities are stored as original strings received from the exchange
    so that CRC32 checksums can be recomputed without float-conversion artifacts.
    """

    def __init__(
        self,
        exchange: Exchange,
        symbol: str,
        instrument_type: InstrumentType,
    ) -> None:
        self.exchange = exchange
        self.symbol = symbol
        self.instrument_type = instrument_type

        self._bids: dict[str, str] = {}  # price_str → qty_str
        self._asks: dict[str, str] = {}

        self.update_id: int = 0
        self.seq: int = 0
        self.last_ts_ms: int = 0
        self._initialized: bool = False

    # ── Apply messages ────────────────────────────────────────────────────────

    def apply_snapshot(
        self,
        bids: list[list[str]],
        asks: list[list[str]],
        update_id: int,
        seq: int,
        ts_ms: int,
    ) -> None:
        self._bids = {p: q for p, q in bids if q != "0"}
        self._asks = {p: q for p, q in asks if q != "0"}
        self.update_id = update_id
        self.seq = seq
        self.last_ts_ms = ts_ms
        self._initialized = True

    def apply_delta(
        self,
        bids: list[list[str]],
        asks: list[list[str]],
        update_id: int,
        seq: int,
        ts_ms: int,
    ) -> bool:
        """
        Apply an incremental update.
        Returns False if a sequence gap is detected — caller should re-subscribe.
        """
        if not self._initialized:
            return True  # silent skip; waiting for snapshot

        if self.update_id != 0 and update_id != self.update_id + 1:
            self._initialized = False
            return False  # sequence gap

        self._apply_side(self._bids, bids)
        self._apply_side(self._asks, asks)
        self.update_id = update_id
        self.seq = seq
        self.last_ts_ms = ts_ms
        return True

    @staticmethod
    def _apply_side(book: dict[str, str], updates: list[list[str]]) -> None:
        for price, qty in updates:
            if qty == "0":
                book.pop(price, None)
            else:
                book[price] = qty

    # ── State queries ─────────────────────────────────────────────────────────

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def best_bid(self) -> float:
        return max((float(p) for p in self._bids), default=0.0)

    @property
    def best_ask(self) -> float:
        return min((float(p) for p in self._asks), default=0.0)

    @property
    def mid(self) -> float:
        bb, ba = self.best_bid, self.best_ask
        return (bb + ba) / 2.0 if bb and ba else 0.0

    @property
    def spread(self) -> float:
        return self.best_ask - self.best_bid

    @property
    def spread_bps(self) -> float:
        m = self.mid
        return self.spread / m * 10_000 if m else 0.0

    def imbalance(self, depth: int = 5) -> float:
        """Bid-ask imbalance in [-1, 1]. Positive = bid-heavy."""
        bids = sorted(self._bids.items(), key=lambda x: float(x[0]), reverse=True)[:depth]
        asks = sorted(self._asks.items(), key=lambda x: float(x[0]))[:depth]
        bid_qty = sum(float(q) for _, q in bids)
        ask_qty = sum(float(q) for _, q in asks)
        total = bid_qty + ask_qty
        return (bid_qty - ask_qty) / total if total else 0.0

    def is_stale(self, max_age_ms: int = 5_000) -> bool:
        if not self._initialized:
            return True
        return (int(time.monotonic() * 1_000) - self.last_ts_ms) > max_age_ms

    # ── Checksum (Bybit CRC32 format) ─────────────────────────────────────────

    def compute_checksum(self) -> int:
        bids_25 = sorted(self._bids.items(), key=lambda x: float(x[0]), reverse=True)[:25]
        asks_25 = sorted(self._asks.items(), key=lambda x: float(x[0]))[:25]
        parts = [f"{p}|{q}" for p, q in bids_25] + [f"{p}|{q}" for p, q in asks_25]
        return zlib.crc32(":".join(parts).encode()) & 0xFFFFFFFF

    def validate_checksum(self, expected: int) -> bool:
        return self.compute_checksum() == expected

    # ── Conversion ────────────────────────────────────────────────────────────

    def to_snapshot(self, depth: int = 20) -> OrderBook:
        bids = sorted(self._bids.items(), key=lambda x: float(x[0]), reverse=True)[:depth]
        asks = sorted(self._asks.items(), key=lambda x: float(x[0]))[:depth]
        return OrderBook(
            exchange=self.exchange,
            symbol=self.symbol,
            instrument_type=self.instrument_type,
            bids=[OrderBookLevel(price=float(p), qty=float(q)) for p, q in bids],
            asks=[OrderBookLevel(price=float(p), qty=float(q)) for p, q in asks],
            ts_ms=self.last_ts_ms,
            seq=self.seq,
        )

    def summary(self) -> BookSummary:
        return BookSummary(
            exchange=self.exchange,
            symbol=self.symbol,
            instrument_type=self.instrument_type,
            best_bid=self.best_bid,
            best_ask=self.best_ask,
            mid=self.mid,
            spread_bps=self.spread_bps,
            imbalance_5=self.imbalance(5),
            ts_ms=self.last_ts_ms,
            is_stale=self.is_stale(),
        )
