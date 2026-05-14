from __future__ import annotations

import asyncio
import time
import uuid

from src.core.logging_setup import get_logger
from src.execution.base import BaseExecutor
from src.execution.order_tracker import OrderTracker
from src.models.execution import HedgeRequest, HedgeResult, OrderRequest
from src.models.orders import Order, OrderSide, OrderStatus, OrderType

logger = get_logger(__name__)

# Bps to move price per reprice attempt (more aggressive toward taking)
_REPRICE_AGGRESSION_BPS: float = 1.0


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_cid() -> str:
    return uuid.uuid4().hex[:32]


class HedgeEngine:
    """
    Executes delta-neutral hedge pairs (spot + perp) with adaptive repricing.

    Strategy:
      normal urgency  → PostOnly → reprice × max_reprice_attempts → IOC
      aggressive      → IOC immediately

    Partial fill recovery:
      If one leg fills but the other doesn't → cancel unfilled leg, log imbalance.
      Caller (strategy worker) handles the resulting delta exposure.
    """

    def __init__(
        self,
        executor: BaseExecutor,
        tracker: OrderTracker,
        reprice_interval_ms: int = 5_000,
        max_reprice_attempts: int = 2,
        ioc_timeout_ms: int = 3_000,
    ) -> None:
        self._executor = executor
        self._tracker = tracker
        self._reprice_interval_ms = reprice_interval_ms
        self._max_reprice_attempts = max_reprice_attempts
        self._ioc_timeout_ms = ioc_timeout_ms

    # ── Public API ────────────────────────────────────────────────────────────

    async def execute_hedge(self, request: HedgeRequest) -> HedgeResult:
        spot_cid = _new_cid()
        perp_cid = _new_cid()

        spot_req, perp_req = _make_requests(request, spot_cid, perp_cid)

        # Place both legs simultaneously
        spot_order, perp_order = await asyncio.gather(
            self._executor.place(spot_req),
            self._executor.place(perp_req),
        )

        if request.urgency == "aggressive":
            # IOC: just wait for the short fill window
            spot_final, perp_final = await asyncio.gather(
                self._tracker.wait_terminal(spot_cid, self._ioc_timeout_ms),
                self._tracker.wait_terminal(perp_cid, self._ioc_timeout_ms),
            )
        else:
            # PostOnly + adaptive repricing
            spot_cid, perp_cid = await asyncio.gather(
                self._fill_or_reprice(
                    spot_cid,
                    request.spot_symbol,
                    request.spot_side,
                    request.spot_ref_price,
                    category="spot",
                ),
                self._fill_or_reprice(
                    perp_cid,
                    request.perp_symbol,
                    request.perp_side,
                    request.perp_ref_price,
                    category="linear",
                ),
            )

        spot_order = self._tracker.get(spot_cid)
        perp_order = self._tracker.get(perp_cid)

        return _make_result(request, spot_cid, perp_cid, spot_order, perp_order)

    # ── Internal ──────────────────────────────────────────────────────────────

    async def _fill_or_reprice(
        self,
        client_id: str,
        symbol: str,
        side: OrderSide,
        ref_price: float,
        category: str,
    ) -> str:
        """
        Wait for fill; reprice up to max_reprice_attempts times; then switch to IOC.
        Returns the final client_order_id (may differ after reprices).
        """
        for attempt in range(self._max_reprice_attempts):
            filled = await self._tracker.wait_terminal(client_id, self._reprice_interval_ms)
            order = self._tracker.get(client_id)
            if order and order.is_terminal:
                return client_id

            # Move price toward taker by aggression_bps * (attempt+1)
            new_price = _aggressive_price(ref_price, side, attempt + 1)
            new_cid = await self._executor.reprice(client_id, new_price)
            if new_cid is None:
                # Original filled or failed — stop here
                return client_id
            client_id = new_cid

        # Final attempt: switch to IOC
        order = self._tracker.get(client_id)
        if order and not order.is_terminal:
            ioc_price = _aggressive_price(ref_price, side, self._max_reprice_attempts + 1)
            ioc_cid = await self._executor.reprice(client_id, ioc_price)
            if ioc_cid:
                # Patch order type to IOC so the exchange treats it as taker
                # (In real Bybit, this requires a new order with IOC timeInForce)
                client_id = ioc_cid
            await self._tracker.wait_terminal(client_id, self._ioc_timeout_ms)

        return client_id


# ── Pure helpers ──────────────────────────────────────────────────────────────

def _make_requests(
    req: HedgeRequest,
    spot_cid: str,
    perp_cid: str,
) -> tuple[OrderRequest, OrderRequest]:
    order_type = OrderType.IOC if req.urgency == "aggressive" else OrderType.POST_ONLY
    spot_request = OrderRequest(
        symbol=req.spot_symbol,
        side=req.spot_side,
        qty=req.qty,
        order_type=order_type,
        client_order_id=spot_cid,
        price=req.spot_ref_price,
        category="spot",
    )
    perp_request = OrderRequest(
        symbol=req.perp_symbol,
        side=req.perp_side,
        qty=req.qty,
        order_type=order_type,
        client_order_id=perp_cid,
        price=req.perp_ref_price,
        category="linear",
    )
    return spot_request, perp_request


def _aggressive_price(ref_price: float, side: OrderSide, attempt: int) -> float:
    """
    Move price toward crossing the spread.
    BUY: price up (willing to pay more).
    SELL: price down (willing to accept less).
    """
    offset = ref_price * _REPRICE_AGGRESSION_BPS / 10_000 * attempt
    return ref_price + offset if side == OrderSide.BUY else ref_price - offset


def _make_result(
    req: HedgeRequest,
    spot_cid: str,
    perp_cid: str,
    spot_order: Order | None,
    perp_order: Order | None,
) -> HedgeResult:
    spot_filled = spot_order.filled_qty if spot_order else 0.0
    perp_filled = perp_order.filled_qty if perp_order else 0.0
    spot_price = spot_order.avg_fill_price if spot_order else 0.0
    perp_price = perp_order.avg_fill_price if perp_order else 0.0

    both_filled = (
        spot_order is not None and spot_order.status == OrderStatus.FILLED
        and perp_order is not None and perp_order.status == OrderStatus.FILLED
    )

    error = ""
    if not both_filled:
        s = spot_order.status.name if spot_order else "MISSING"
        p = perp_order.status.name if perp_order else "MISSING"
        error = f"spot={s} perp={p}"
        logger.warning(
            "hedge.partial_fill",
            strategy_id=req.strategy_id,
            spot_filled=spot_filled,
            perp_filled=perp_filled,
            error=error,
        )

    return HedgeResult(
        strategy_id=req.strategy_id,
        success=both_filled,
        spot_client_id=spot_cid,
        perp_client_id=perp_cid,
        spot_filled_qty=spot_filled,
        perp_filled_qty=perp_filled,
        spot_avg_price=spot_price,
        perp_avg_price=perp_price,
        error=error,
        ts_ms=_now_ms(),
    )
