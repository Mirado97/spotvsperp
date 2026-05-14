from __future__ import annotations

import msgspec

from src.models.market import Exchange


class LiquidationEvent(msgspec.Struct, frozen=True, gc=False):
    """Single liquidation order as broadcast by the exchange."""
    exchange: Exchange
    symbol: str
    side: str      # "long" | "short"  — position that was liquidated
    qty: float
    price: float
    value_usd: float   # qty * price
    ts_ms: int
