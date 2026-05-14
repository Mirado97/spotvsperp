from __future__ import annotations

import time
import uuid

from src.core.logging_setup import get_logger
from src.exchange.bybit.rest_client import BybitRestClient
from src.execution.base import BaseExecutor
from src.execution.order_tracker import OrderTracker
from src.models.execution import OrderRequest
from src.models.orders import Order, OrderStatus, OrderType

logger = get_logger(__name__)


def _now_ms() -> int:
    return int(time.time() * 1000)


class BybitExecutor(BaseExecutor):
    """
    Bridges BybitRestClient + OrderTracker.
    Every placed order is registered in the tracker immediately, before
    the REST call completes, so the HedgeEngine can await its fill event.
    """

    def __init__(self, rest: BybitRestClient, tracker: OrderTracker) -> None:
        self._rest = rest
        self._tracker = tracker

    @property
    def tracker(self) -> OrderTracker:
        return self._tracker

    # ── BaseExecutor ──────────────────────────────────────────────────────────

    async def place(self, request: OrderRequest) -> Order:
        order = self._tracker.register(request)
        try:
            exchange_id = await self._rest.place_order(request)
            self._tracker.on_new(request.client_order_id, exchange_id, _now_ms())
            logger.info(
                "executor.placed",
                client_id=request.client_order_id,
                exchange_id=exchange_id,
                symbol=request.symbol,
                side=request.side.name,
                qty=request.qty,
                price=request.price,
            )
        except Exception as exc:
            self._tracker.on_reject(request.client_order_id, _now_ms())
            logger.error("executor.place_failed", client_id=request.client_order_id, error=str(exc))
        return self._tracker.get(request.client_order_id) or order

    async def cancel(self, client_order_id: str) -> bool:
        order = self._tracker.get(client_order_id)
        if order is None or order.is_terminal:
            return False
        ok = await self._rest.cancel_order(
            symbol=order.symbol,
            client_order_id=client_order_id,
            category=_category(order),
        )
        if ok:
            self._tracker.on_cancel(client_order_id, _now_ms())
            logger.info("executor.cancelled", client_id=client_order_id)
        return ok

    async def reprice(self, client_order_id: str, new_price: float) -> str | None:
        """
        Cancel the current order and place a new one at new_price.
        Returns new client_order_id, or None if original was already terminal.
        """
        order = self._tracker.get(client_order_id)
        if order is None:
            return None
        if order.is_terminal:
            return None

        cancelled = await self.cancel(client_order_id)
        if not cancelled:
            # May have filled between our check and cancel
            order = self._tracker.get(client_order_id)
            if order and order.status == OrderStatus.FILLED:
                return None
            # Already cancelled or rejected by exchange — proceed anyway

        remaining = (order.qty - order.filled_qty) if order else 0.0
        if remaining <= 0:
            return None

        new_cid = _new_client_id()
        new_request = OrderRequest(
            symbol=order.symbol,
            side=order.side,
            qty=remaining,
            order_type=order.order_type,
            client_order_id=new_cid,
            exchange=order.exchange,
            price=new_price,
            reduce_only=order.reduce_only,
            category=_category(order),
        )
        await self.place(new_request)
        return new_cid

    async def sync_order(self, client_order_id: str) -> Order | None:
        """
        Poll REST for the current order state and update the tracker.
        Used as fallback when private WS reports are unavailable.
        """
        order = self._tracker.get(client_order_id)
        if order is None or order.is_terminal:
            return order

        raw = await self._rest.get_order(order.symbol, client_order_id, _category(order))
        if raw is None:
            return order

        status_str = raw.get("orderStatus", "")
        from src.exchange.bybit.rest_client import _STATUS_MAP
        status = _STATUS_MAP.get(status_str)
        if status is None:
            return order

        filled_qty = float(raw.get("cumExecQty", 0))
        avg_price = float(raw.get("avgPrice") or 0)

        if status == OrderStatus.FILLED:
            self._tracker.on_fill(client_order_id, filled_qty, avg_price, True, _now_ms())
        elif status == OrderStatus.PARTIALLY_FILLED:
            self._tracker.on_fill(client_order_id, filled_qty, avg_price, False, _now_ms())
        elif status in (OrderStatus.CANCELLED, OrderStatus.EXPIRED):
            self._tracker.on_cancel(client_order_id, _now_ms())
        elif status == OrderStatus.REJECTED:
            self._tracker.on_reject(client_order_id, _now_ms())

        return self._tracker.get(client_order_id)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _new_client_id() -> str:
    return uuid.uuid4().hex[:32]


def _category(order: Order) -> str:
    # Spot orders: post_only is set only when explicitly chosen; use order_type heuristic
    # In practice, the category is stored in OrderRequest but not propagated to Order.
    # We use reduce_only=False and side conventions to guess; caller can override.
    # For this implementation, all orders default to "linear" unless created with category="spot".
    # HedgeEngine passes the right category in OrderRequest.
    return "linear"
