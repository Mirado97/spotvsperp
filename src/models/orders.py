from __future__ import annotations

from enum import IntEnum

import msgspec

from src.models.market import Exchange, InstrumentType


class OrderSide(IntEnum):
    BUY = 1
    SELL = 2


class OrderType(IntEnum):
    LIMIT = 1
    MARKET = 2
    POST_ONLY = 3
    IOC = 4
    FOK = 5


class OrderStatus(IntEnum):
    PENDING = 0
    NEW = 1
    PARTIALLY_FILLED = 2
    FILLED = 3
    CANCELLED = 4
    REJECTED = 5
    EXPIRED = 6


class Order(msgspec.Struct):
    exchange: Exchange
    symbol: str
    order_id: str
    client_order_id: str
    side: OrderSide
    order_type: OrderType
    qty: float
    price: float
    status: OrderStatus
    filled_qty: float = 0.0
    avg_fill_price: float = 0.0
    created_ts: int = 0
    updated_ts: int = 0
    reduce_only: bool = False
    post_only: bool = False

    @property
    def remaining_qty(self) -> float:
        return self.qty - self.filled_qty

    @property
    def is_active(self) -> bool:
        return self.status in (OrderStatus.NEW, OrderStatus.PARTIALLY_FILLED)

    @property
    def is_terminal(self) -> bool:
        return self.status in (OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED, OrderStatus.EXPIRED)


class Fill(msgspec.Struct, frozen=True, gc=False):
    exchange: Exchange
    symbol: str
    order_id: str
    fill_id: str
    side: OrderSide
    price: float
    qty: float
    fee: float
    fee_currency: str
    ts_ms: int
    instrument_type: InstrumentType = InstrumentType.PERPETUAL
