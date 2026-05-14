from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.exchange.bybit import constants as C
from src.exchange.orderbook import OrderBookState
from src.models.market import Exchange, InstrumentType

logger = get_logger(__name__)

_ResubCallback = Callable[[str, str, int], Awaitable[None]]


class BybitOrderBookHandler:
    """
    Manages all Bybit orderbook states for one category (SPOT or PERP).

    Responsibilities:
    - Apply snapshot / delta messages
    - Validate CRC32 checksums after every delta
    - Detect sequence gaps and trigger re-subscription for a fresh snapshot
    - Publish updated OrderBook snapshots to MarketDataBus
    """

    def __init__(
        self,
        bus: MarketDataBus,
        category: str,                     # "SPOT" | "PERP"
        instrument_type: InstrumentType,
        on_resub: _ResubCallback,          # called when (symbol, category, depth) needs re-sub
    ) -> None:
        self._bus = bus
        self._category = category
        self._instrument_type = instrument_type
        self._on_resub = on_resub
        self._books: dict[str, OrderBookState] = {}  # symbol → state

    # ── Public ────────────────────────────────────────────────────────────────

    def get_book(self, symbol: str) -> OrderBookState | None:
        return self._books.get(symbol)

    async def handle(self, data: dict[str, Any], ts_ms: int) -> None:
        topic: str = data.get("topic", "")
        msg_type: str = data.get("type", "")
        raw = data.get("data", {})

        # topic: "orderbook.{depth}.{symbol}"
        parts = topic.split(".")
        if len(parts) != 3:
            return
        try:
            depth = int(parts[1])
        except ValueError:
            return
        symbol = parts[2]

        # Bybit: u=1 in a delta means it carries a full snapshot
        update_id = int(raw.get("u", 0))
        if msg_type == "delta" and update_id == 1:
            msg_type = "snapshot"

        if msg_type == "snapshot":
            await self._apply_snapshot(symbol, raw, update_id, ts_ms)

        elif msg_type == "delta":
            await self._apply_delta(symbol, raw, update_id, ts_ms, depth)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _apply_snapshot(
        self,
        symbol: str,
        raw: dict[str, Any],
        update_id: int,
        ts_ms: int,
    ) -> None:
        book = OrderBookState(
            exchange=Exchange.BYBIT,
            symbol=symbol,
            instrument_type=self._instrument_type,
        )
        book.apply_snapshot(
            bids=raw.get("b", []),
            asks=raw.get("a", []),
            update_id=update_id,
            seq=raw.get("seq", 0),
            ts_ms=ts_ms,
        )

        if cts := raw.get("cts"):
            if not book.validate_checksum(int(cts)):
                logger.warning("ob.checksum_mismatch_snapshot", symbol=symbol, category=self._category)

        self._books[symbol] = book
        self._publish(book)
        logger.debug("ob.snapshot_applied", symbol=symbol, category=self._category, bids=len(raw.get("b", [])), asks=len(raw.get("a", [])))

    async def _apply_delta(
        self,
        symbol: str,
        raw: dict[str, Any],
        update_id: int,
        ts_ms: int,
        depth: int,
    ) -> None:
        book = self._books.get(symbol)
        if book is None:
            return

        ok = book.apply_delta(
            bids=raw.get("b", []),
            asks=raw.get("a", []),
            update_id=update_id,
            seq=raw.get("seq", 0),
            ts_ms=ts_ms,
        )

        if not ok:
            logger.warning("ob.sequence_gap", symbol=symbol, category=self._category, expected=book.update_id + 1, got=update_id)
            await self._on_resub(symbol, self._category, depth)
            return

        if cts := raw.get("cts"):
            if not book.validate_checksum(int(cts)):
                logger.warning("ob.checksum_mismatch_delta", symbol=symbol, category=self._category)
                book._initialized = False
                await self._on_resub(symbol, self._category, depth)
                return

        self._publish(book)

    def _publish(self, book: OrderBookState) -> None:
        snapshot = book.to_snapshot()
        self._bus.publish(C.bus_orderbook_topic("BYBIT", book.symbol, self._category), snapshot)
