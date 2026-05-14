from __future__ import annotations

import asyncio
import time

from src.models.execution import OrderRequest
from src.models.orders import Fill, Order, OrderSide, OrderStatus, OrderType
from src.models.market import Exchange


def _now_ms() -> int:
    return int(time.time() * 1000)


class OrderTracker:
    """
    In-memory state machine for active orders.
    asyncio.Event per order lets the hedge engine await fills without polling.

    All mutations are synchronous (single-threaded asyncio).
    """

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._events: dict[str, asyncio.Event] = {}

    # ── Mutations ─────────────────────────────────────────────────────────────

    def register(self, request: OrderRequest) -> Order:
        order = Order(
            exchange=request.exchange,
            symbol=request.symbol,
            order_id="",
            client_order_id=request.client_order_id,
            side=request.side,
            order_type=request.order_type,
            qty=request.qty,
            price=request.price,
            status=OrderStatus.PENDING,
            reduce_only=request.reduce_only,
            post_only=(request.order_type == OrderType.POST_ONLY),
            created_ts=_now_ms(),
        )
        self._orders[request.client_order_id] = order
        self._events[request.client_order_id] = asyncio.Event()
        return order

    def on_new(self, client_id: str, exchange_id: str, ts_ms: int) -> None:
        order = self._orders.get(client_id)
        if order is None or order.is_terminal:
            return
        self._orders[client_id] = _replace(order, order_id=exchange_id, status=OrderStatus.NEW, updated_ts=ts_ms)

    def on_fill(
        self,
        client_id: str,
        filled_qty: float,
        avg_price: float,
        is_fully_filled: bool,
        ts_ms: int,
    ) -> None:
        order = self._orders.get(client_id)
        if order is None or order.is_terminal:
            return
        status = OrderStatus.FILLED if is_fully_filled else OrderStatus.PARTIALLY_FILLED
        self._orders[client_id] = _replace(
            order,
            status=status,
            filled_qty=filled_qty,
            avg_fill_price=avg_price,
            updated_ts=ts_ms,
        )
        if is_fully_filled:
            self._events[client_id].set()

    def on_cancel(self, client_id: str, ts_ms: int) -> None:
        order = self._orders.get(client_id)
        if order is None or order.is_terminal:
            return
        self._orders[client_id] = _replace(order, status=OrderStatus.CANCELLED, updated_ts=ts_ms)
        self._events[client_id].set()

    def on_reject(self, client_id: str, ts_ms: int) -> None:
        order = self._orders.get(client_id)
        if order is None or order.is_terminal:
            return
        self._orders[client_id] = _replace(order, status=OrderStatus.REJECTED, updated_ts=ts_ms)
        self._events[client_id].set()

    # ── Queries ───────────────────────────────────────────────────────────────

    def get(self, client_id: str) -> Order | None:
        return self._orders.get(client_id)

    def active_orders(self) -> list[Order]:
        return [o for o in self._orders.values() if o.is_active]

    def is_stale(self, client_id: str, timeout_ms: int, now_ms: int | None = None) -> bool:
        order = self._orders.get(client_id)
        if order is None or order.is_terminal:
            return False
        elapsed = (now_ms or _now_ms()) - order.created_ts
        return elapsed > timeout_ms

    async def wait_terminal(self, client_id: str, timeout_ms: int) -> bool:
        """
        Await until the order reaches a terminal state, or timeout.
        Returns True if terminal, False if timed-out.
        """
        order = self._orders.get(client_id)
        if order is None:
            return False
        if order.is_terminal:
            return True
        event = self._events.get(client_id)
        if event is None:
            return False
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout_ms / 1000.0)
            return True
        except asyncio.TimeoutError:
            return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _replace(order: Order, **kwargs) -> Order:
    """Mutate Order in place (msgspec.Struct non-frozen supports setattr)."""
    for k, v in kwargs.items():
        setattr(order, k, v)
    return order
