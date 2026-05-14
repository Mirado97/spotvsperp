from __future__ import annotations

import asyncio

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.execution.order_tracker import OrderTracker
from src.risk.engine import RiskEngine
from src.risk.models import RiskLimits
from src.strategy.carry_worker import CarryWorker
from src.backtest.execution import SimulatedExecutor, TradeCollector, RecordingHedgeEngine
from src.backtest.metrics import compute_metrics
from src.backtest.models import BacktestConfig, BacktestResult, MarketEvent

logger = get_logger(__name__)


class BacktestEngine:
    """
    Replays market events through the live strategy logic with a simulated executor.

    The same CarryWorker + HedgeEngine code runs against synthetic fills
    with configurable slippage and latency.

    Usage:
        engine = BacktestEngine(config)
        result = await engine.run(events)
    """

    def __init__(self, config: BacktestConfig) -> None:
        self._cfg = config

    async def run(self, events: list[MarketEvent]) -> BacktestResult:
        if not events:
            empty = compute_metrics([], self._cfg.initial_equity)
            return BacktestResult(config=self._cfg, trades=[], metrics=empty)

        bus = MarketDataBus()
        tracker = OrderTracker()
        executor = SimulatedExecutor(
            tracker,
            slippage_bps=self._cfg.slippage_bps,
            latency_ms=self._cfg.latency_ms,
        )
        collector = TradeCollector(fee_bps=self._cfg.taker_fee_bps)
        hedge_engine = RecordingHedgeEngine(
            executor, tracker, collector,
            reprice_interval_ms=100,
            max_reprice_attempts=0,
        )
        risk_engine = RiskEngine(
            bus=bus,
            limits=RiskLimits(),
            initial_equity=self._cfg.initial_equity,
        )
        worker = CarryWorker(
            config=self._cfg.strategy_config,
            bus=bus,
            hedge_engine=hedge_engine,
            risk_engine=risk_engine,
        )

        symbol = self._cfg.strategy_config.symbol
        exchange = self._cfg.strategy_config.exchange

        task = asyncio.create_task(worker.run(), name=f"backtest_worker_{symbol}")
        await asyncio.sleep(0)

        for event in events:
            if event.funding:
                bus.publish(f"funding_analysis.{exchange}.{symbol}", event.funding)
            if event.signal:
                bus.publish(f"signal.{exchange}.{symbol}", event.signal)
            bus.publish(f"basis.{exchange}.{symbol}", event.basis)

            # Yield enough times for the worker to process and potentially execute
            for _ in range(4):
                await asyncio.sleep(0)
            if self._cfg.latency_ms > 0:
                await asyncio.sleep(self._cfg.latency_ms / 1_000 * 1.5)

        worker.stop()
        await asyncio.wait_for(task, timeout=10.0)

        ts_end = events[-1].basis.ts_ms
        collector.flush_open(ts_end)

        metrics = compute_metrics(collector.trades, self._cfg.initial_equity)
        logger.info(
            "backtest.complete",
            symbol=symbol,
            periods=len(events),
            trades=metrics.total_trades,
            net_pnl=round(metrics.total_net_pnl, 2),
            return_pct=round(metrics.return_pct * 100, 3),
        )
        return BacktestResult(config=self._cfg, trades=collector.trades, metrics=metrics)
