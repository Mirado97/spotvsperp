from __future__ import annotations

import msgspec

from src.models.market import Exchange
from src.models.orders import OrderSide, OrderType


class OrderRequest(msgspec.Struct, frozen=True, gc=False):
    """Instruction to submit a single order."""
    symbol: str
    side: OrderSide
    qty: float
    order_type: OrderType
    client_order_id: str
    exchange: Exchange = Exchange.BYBIT
    price: float = 0.0          # 0 = market / no price constraint
    reduce_only: bool = False
    category: str = "linear"    # "spot" | "linear"


class HedgeRequest(msgspec.Struct, frozen=True, gc=False):
    """
    Request to open or close a delta-neutral pair (spot + perp).
    strategy_id links this back to the originating strategy worker.
    """
    spot_symbol: str
    perp_symbol: str
    spot_side: OrderSide       # BUY for long-carry, SELL to close
    perp_side: OrderSide       # SELL for long-carry, BUY to close
    qty: float                 # base currency quantity (same for both legs)
    spot_ref_price: float      # reference mid price for spot
    perp_ref_price: float      # reference mid price for perp
    strategy_id: str
    urgency: str = "normal"    # "normal" → PostOnly+reprice; "aggressive" → IOC


class HedgeResult(msgspec.Struct, frozen=True, gc=False):
    """Outcome of a hedge execution attempt."""
    strategy_id: str
    success: bool
    spot_client_id: str
    perp_client_id: str
    spot_filled_qty: float
    perp_filled_qty: float
    spot_avg_price: float
    perp_avg_price: float
    error: str = ""
    ts_ms: int = 0

    @property
    def is_fully_hedged(self) -> bool:
        if self.spot_filled_qty == 0:
            return False
        delta = abs(self.spot_filled_qty - self.perp_filled_qty)
        return delta < self.spot_filled_qty * 0.01  # within 1%

    @property
    def realized_basis(self) -> float:
        """Actual basis captured: (perp_price - spot_price) / spot_price."""
        if self.spot_avg_price == 0:
            return 0.0
        return (self.perp_avg_price - self.spot_avg_price) / self.spot_avg_price
