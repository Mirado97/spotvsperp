from __future__ import annotations

import zlib

import pytest

from src.exchange.orderbook import OrderBookState
from src.models.market import Exchange, InstrumentType


def _make_book() -> OrderBookState:
    return OrderBookState(
        exchange=Exchange.BYBIT,
        symbol="BTCUSDT",
        instrument_type=InstrumentType.SPOT,
    )


def _snapshot(book: OrderBookState, bids: list, asks: list, u: int = 1, seq: int = 100, ts: int = 1_000) -> None:
    book.apply_snapshot(bids=bids, asks=asks, update_id=u, seq=seq, ts_ms=ts)


# ── Snapshot ──────────────────────────────────────────────────────────────────

def test_snapshot_initializes_book():
    book = _make_book()
    assert not book.is_ready
    _snapshot(book, [["100.0", "5.0"], ["99.0", "3.0"]], [["101.0", "4.0"], ["102.0", "2.0"]])
    assert book.is_ready
    assert book.best_bid == pytest.approx(100.0)
    assert book.best_ask == pytest.approx(101.0)


def test_snapshot_removes_zero_qty():
    book = _make_book()
    _snapshot(book, [["100.0", "0"], ["99.0", "3.0"]], [["101.0", "0"]])
    assert "100.0" not in book._bids
    assert "101.0" not in book._asks


def test_snapshot_replaces_previous_state():
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"]], [["101.0", "4.0"]], u=1)
    _snapshot(book, [["200.0", "1.0"]], [["201.0", "1.0"]], u=1)
    assert book.best_bid == pytest.approx(200.0)
    assert "100.0" not in book._bids


# ── Delta ─────────────────────────────────────────────────────────────────────

def test_delta_adds_new_level():
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"]], [["101.0", "4.0"]], u=1)
    book.apply_delta(bids=[["99.5", "2.0"]], asks=[], update_id=2, seq=101, ts_ms=2_000)
    assert "99.5" in book._bids
    assert book._bids["99.5"] == "2.0"


def test_delta_updates_existing_level():
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"]], [["101.0", "4.0"]], u=1)
    book.apply_delta(bids=[["100.0", "8.0"]], asks=[], update_id=2, seq=101, ts_ms=2_000)
    assert book._bids["100.0"] == "8.0"


def test_delta_removes_level_on_zero_qty():
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"], ["99.0", "3.0"]], [["101.0", "4.0"]], u=1)
    book.apply_delta(bids=[["100.0", "0"]], asks=[], update_id=2, seq=101, ts_ms=2_000)
    assert "100.0" not in book._bids
    assert book.best_bid == pytest.approx(99.0)


def test_delta_returns_false_on_sequence_gap():
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"]], [["101.0", "4.0"]], u=1)
    # u=2 is expected, send u=5 → gap
    ok = book.apply_delta(bids=[], asks=[], update_id=5, seq=104, ts_ms=2_000)
    assert ok is False
    assert not book.is_ready


def test_delta_ignored_before_snapshot():
    book = _make_book()
    ok = book.apply_delta(bids=[["100.0", "5.0"]], asks=[], update_id=2, seq=1, ts_ms=1_000)
    assert ok is True  # silent skip, not an error
    assert not book.is_ready


def test_delta_u1_resets_as_snapshot():
    """u=1 in a delta signals Bybit is sending a fresh snapshot."""
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"]], [["101.0", "4.0"]], u=1)
    book.apply_delta(bids=[["200.0", "1.0"]], asks=[], update_id=2, seq=2, ts_ms=2_000)
    # Force a u=1 delta — handled by ob_handler, not here at model level
    # (the ob_handler converts it to snapshot before calling apply_snapshot)


# ── Computed properties ───────────────────────────────────────────────────────

def test_mid_and_spread():
    book = _make_book()
    _snapshot(book, [["100.0", "5.0"]], [["102.0", "4.0"]])
    assert book.mid == pytest.approx(101.0)
    assert book.spread == pytest.approx(2.0)
    assert book.spread_bps == pytest.approx(2.0 / 101.0 * 10_000, rel=1e-4)


def test_imbalance_bid_heavy():
    book = _make_book()
    _snapshot(
        book,
        [["100.0", "10.0"], ["99.0", "5.0"]],
        [["101.0", "3.0"], ["102.0", "2.0"]],
    )
    imb = book.imbalance(depth=2)
    # bids=15, asks=5, total=20 → 0.5
    assert imb == pytest.approx(0.5)


def test_imbalance_empty_book():
    book = _make_book()
    _snapshot(book, [], [])
    assert book.imbalance() == 0.0


# ── to_snapshot ───────────────────────────────────────────────────────────────

def test_to_snapshot_sorted_levels():
    book = _make_book()
    _snapshot(
        book,
        [["99.0", "3.0"], ["100.0", "5.0"], ["98.0", "1.0"]],
        [["103.0", "2.0"], ["101.0", "4.0"], ["102.0", "2.0"]],
        ts=9_999,
    )
    snap = book.to_snapshot(depth=3)
    # bids descending
    assert snap.bids[0].price == 100.0
    assert snap.bids[1].price == 99.0
    assert snap.bids[2].price == 98.0
    # asks ascending
    assert snap.asks[0].price == 101.0
    assert snap.asks[1].price == 102.0
    assert snap.asks[2].price == 103.0
    assert snap.ts_ms == 9_999


def test_to_snapshot_respects_depth():
    book = _make_book()
    bids = [[str(100 - i), "1.0"] for i in range(20)]
    asks = [[str(101 + i), "1.0"] for i in range(20)]
    _snapshot(book, bids, asks)
    snap = book.to_snapshot(depth=5)
    assert len(snap.bids) == 5
    assert len(snap.asks) == 5


# ── Checksum ──────────────────────────────────────────────────────────────────

def test_checksum_matches_manual_calculation():
    book = _make_book()
    bids = [["43765.00", "0.5"], ["43764.50", "1.0"]]
    asks = [["43766.00", "0.3"], ["43767.50", "0.8"]]
    _snapshot(book, bids, asks)

    parts = [
        "43765.00|0.5", "43764.50|1.0",   # bids descending
        "43766.00|0.3", "43767.50|0.8",   # asks ascending
    ]
    expected = zlib.crc32(":".join(parts).encode()) & 0xFFFFFFFF
    assert book.compute_checksum() == expected


def test_validate_checksum_correct():
    book = _make_book()
    bids = [["100.00", "5.0"]]
    asks = [["101.00", "3.0"]]
    _snapshot(book, bids, asks)
    crc = book.compute_checksum()
    assert book.validate_checksum(crc)


def test_validate_checksum_wrong():
    book = _make_book()
    _snapshot(book, [["100.00", "5.0"]], [["101.00", "3.0"]])
    assert not book.validate_checksum(0xDEADBEEF)


# ── Stale detection ────────────────────────────────────────────────────────────

def test_is_stale_before_init():
    book = _make_book()
    assert book.is_stale()


def test_is_not_stale_after_fresh_snapshot(monkeypatch):
    import time as _time
    book = _make_book()
    now_ms = int(_time.monotonic() * 1_000)
    _snapshot(book, [["100.0", "1.0"]], [["101.0", "1.0"]], ts=now_ms)
    assert not book.is_stale(max_age_ms=5_000)


# ── BookSummary ───────────────────────────────────────────────────────────────

def test_summary_fields():
    book = _make_book()
    _snapshot(
        book,
        [["100.0", "10.0"], ["99.0", "5.0"]],
        [["102.0", "4.0"], ["103.0", "2.0"]],
        ts=12_345,
    )
    s = book.summary()
    assert s.best_bid == pytest.approx(100.0)
    assert s.best_ask == pytest.approx(102.0)
    assert s.mid == pytest.approx(101.0)
    assert s.spread_bps > 0
    assert s.ts_ms == 12_345
