from __future__ import annotations

from enum import IntEnum

import msgspec

from src.models.market import Exchange


class PositionSide(IntEnum):
    NONE = 0
    LONG = 1
    SHORT = 2


class Position(msgspec.Struct):
    exchange: Exchange
    symbol: str
    side: PositionSide
    size: float           # absolute quantity in base currency
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: float = 1.0
    liquidation_price: float = 0.0
    ts_ms: int = 0

    @property
    def notional_usd(self) -> float:
        return self.size * self.mark_price

    @property
    def pnl_pct(self) -> float:
        if self.entry_price == 0:
            return 0.0
        diff = self.mark_price - self.entry_price
        if self.side == PositionSide.SHORT:
            diff = -diff
        return diff / self.entry_price


class HedgePosition(msgspec.Struct):
    """
    Delta-neutral pair: long spot + short perp (carry trade),
    or short spot + long perp (reverse basis).
    """
    symbol: str
    spot: Position
    perp: Position
    strategy_id: str
    open_ts: int = 0

    @property
    def spot_delta(self) -> float:
        return self.spot.size if self.spot.side == PositionSide.LONG else -self.spot.size

    @property
    def perp_delta(self) -> float:
        return self.perp.size if self.perp.side == PositionSide.LONG else -self.perp.size

    @property
    def net_delta(self) -> float:
        return self.spot_delta + self.perp_delta

    @property
    def is_delta_neutral(self) -> bool:
        if self.spot.size == 0:
            return True
        return abs(self.net_delta) < self.spot.size * 0.01  # within 1%

    @property
    def total_notional_usd(self) -> float:
        return self.spot.notional_usd + self.perp.notional_usd

    @property
    def total_pnl(self) -> float:
        return self.spot.unrealized_pnl + self.perp.unrealized_pnl
