from __future__ import annotations

import asyncio
import dataclasses
import time

from src.execution.base import BaseExecutor
from src.execution.hedge_engine import HedgeEngine
from src.execution.order_tracker import OrderTracker
from src.models.execution import HedgeRequest, HedgeResult, OrderRequest
from src.models.orders import Order, OrderSide
from src.backtest.models import TradeRecord


# ── Simulated executor ────────────────────────────────────────────────────────

class SimulatedExecutor(BaseExecutor):
    """
    Fills every order instantly at reference_price ± slippage.

    BUY  fills above reference: price * (1 + slippage_factor)
    SELL fills below reference: price * (1 - slippage_factor)
    """

    def __init__(
        self,
        tracker: OrderTracker,
        slippage_bps: float = 2.0,
        latency_ms: float = 0.0,
    ) -> None:
        self._tracker = tracker
        self._slippage = slippage_bps / 10_000
        self._latency_s = latency_ms / 1_000

    async def place(self, request: OrderRequest) -> Order:
        if self._latency_s > 0:
            await asyncio.sleep(self._latency_s)

        ref = request.price if request.price > 0 else 1.0
        if request.side == OrderSide.BUY:
            fill_price = ref * (1.0 + self._slippage)
        else:
            fill_price = ref * (1.0 - self._slippage)

        order = self._tracker.register(request)
        self._tracker.on_new(request.client_order_id, f"sim_{request.client_order_id}", 0)
        self._tracker.on_fill(request.client_order_id, request.qty, fill_price, True, 1)
        return self._tracker.get(request.client_order_id)

    async def cancel(self, client_order_id: str) -> bool:
        order = self._tracker.get(client_order_id)
        if order and not order.is_terminal:
            self._tracker.on_cancel(client_order_id, 0)
            return True
        return False

    async def reprice(self, client_order_id: str, new_price: float) -> str | None:
        return None  # instant fills don't need repricing


# ── Trade collector ───────────────────────────────────────────────────────────

@dataclasses.dataclass
class _OpenPosition:
    strategy_id: str
    symbol: str
    entry_ts_ms: int
    spot_entry: float
    perp_entry: float
    qty: float
    entry_basis: float


class TradeCollector:
    """
    Intercepts HedgeEngine results to build TradeRecord objects.

    Called by RecordingHedgeEngine on each successful hedge execution.
    """

    def __init__(self, fee_bps: float = 6.0) -> None:
        self._fee_rate = fee_bps / 10_000
        self.trades: list[TradeRecord] = []
        self._open: dict[str, _OpenPosition] = {}

    def on_entry(self, request: HedgeRequest, result: HedgeResult, ts_ms: int) -> None:
        pos = _OpenPosition(
            strategy_id=result.strategy_id,
            symbol=request.spot_symbol,
            entry_ts_ms=ts_ms,
            spot_entry=result.spot_avg_price,
            perp_entry=result.perp_avg_price,
            qty=result.spot_filled_qty,
            entry_basis=(result.perp_avg_price - result.spot_avg_price) / result.spot_avg_price,
        )
        self._open[result.strategy_id] = pos

    def on_exit(self, result: HedgeResult, ts_ms: int) -> None:
        # strategy_id for exit is "{base}_exit" → match by base
        base_id = result.strategy_id.replace("_exit", "")
        pos = self._open.pop(base_id, None)
        if pos is None:
            return

        # PnL: long spot / short perp carry trade
        # profit from spot appreciating + basis compressing
        spot_pnl = pos.qty * (result.spot_avg_price - pos.spot_entry)
        perp_pnl = pos.qty * (pos.perp_entry - result.perp_avg_price)
        gross_pnl = spot_pnl + perp_pnl

        # Fees: 4 orders total (2 entry + 2 exit), each on qty×price
        avg_price = (pos.spot_entry + result.spot_avg_price) / 2
        fees = 4.0 * pos.qty * avg_price * self._fee_rate
        exit_basis = (result.perp_avg_price - result.spot_avg_price) / result.spot_avg_price

        self.trades.append(TradeRecord(
            strategy_id=base_id,
            symbol=pos.symbol,
            entry_ts_ms=pos.entry_ts_ms,
            exit_ts_ms=ts_ms,
            spot_entry=pos.spot_entry,
            perp_entry=pos.perp_entry,
            spot_exit=result.spot_avg_price,
            perp_exit=result.perp_avg_price,
            qty=pos.qty,
            entry_basis=pos.entry_basis,
            exit_basis=exit_basis,
            gross_pnl=gross_pnl,
            fees=fees,
            net_pnl=gross_pnl - fees,
            periods_held=0,  # filled by caller if available
        ))

    def flush_open(self, ts_ms: int) -> None:
        """Mark any still-open positions at end of backtest."""
        for pos in self._open.values():
            self.trades.append(TradeRecord(
                strategy_id=pos.strategy_id,
                symbol=pos.symbol,
                entry_ts_ms=pos.entry_ts_ms,
                exit_ts_ms=None,
                spot_entry=pos.spot_entry,
                perp_entry=pos.perp_entry,
                spot_exit=None,
                perp_exit=None,
                qty=pos.qty,
                entry_basis=pos.entry_basis,
                exit_basis=None,
                gross_pnl=0.0,
                fees=0.0,
                net_pnl=0.0,
                periods_held=0,
                is_open=True,
            ))
        self._open.clear()


# ── Recording hedge engine ────────────────────────────────────────────────────

class RecordingHedgeEngine(HedgeEngine):
    """
    HedgeEngine subclass that intercepts execute_hedge results
    and forwards them to a TradeCollector.
    """

    def __init__(
        self,
        executor: BaseExecutor,
        tracker: OrderTracker,
        collector: TradeCollector,
        reprice_interval_ms: int = 100,
        max_reprice_attempts: int = 0,
    ) -> None:
        super().__init__(executor, tracker, reprice_interval_ms, max_reprice_attempts)
        self._collector = collector

    async def execute_hedge(self, request: HedgeRequest) -> HedgeResult:
        result = await super().execute_hedge(request)
        if result.success:
            ts = int(time.time() * 1000)
            if request.strategy_id.endswith("_exit"):
                self._collector.on_exit(result, ts)
            else:
                self._collector.on_entry(request, result, ts)
        return result
