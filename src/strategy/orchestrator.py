from __future__ import annotations

import asyncio

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.execution.hedge_engine import HedgeEngine
from src.execution.order_tracker import OrderTracker
from src.risk.engine import RiskEngine
from src.strategy.carry_worker import CarryWorker
from src.strategy.models import StrategyConfig, WorkerStatus
from src.strategy.watchdog import WorkerWatchdog

logger = get_logger(__name__)


class StrategyOrchestrator:
    """
    Creates and supervises CarryWorker tasks for all configured symbols.

    Responsibilities:
      - Start/stop all workers.
      - Forward emergency_stop signals to all workers.
      - Run a WorkerWatchdog that auto-restarts crashed workers.
      - Expose aggregate status for monitoring.

    Supports 500+ symbols: each worker is a lightweight asyncio task.
    """

    def __init__(
        self,
        bus: MarketDataBus,
        hedge_engine: HedgeEngine,
        risk_engine: RiskEngine,
        watchdog_timeout_s: float = 30.0,
        watchdog_interval_s: float = 10.0,
    ) -> None:
        self._bus = bus
        self._hedge_engine = hedge_engine
        self._risk_engine = risk_engine
        self._watchdog_timeout = watchdog_timeout_s
        self._watchdog_interval = watchdog_interval_s

        self._configs: dict[str, StrategyConfig] = {}
        self._workers: dict[str, CarryWorker] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._watchdog: WorkerWatchdog | None = None
        self._system_tasks: list[asyncio.Task] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self, configs: list[StrategyConfig]) -> None:
        for cfg in configs:
            self._configs[cfg.symbol] = cfg
            worker, task = self._spawn(cfg.symbol)
            self._workers[cfg.symbol] = worker
            self._tasks[cfg.symbol] = task

        self._watchdog = WorkerWatchdog(
            workers=self._workers,
            tasks=self._tasks,
            factory_fn=self._spawn,
            heartbeat_timeout_s=self._watchdog_timeout,
            check_interval_s=self._watchdog_interval,
        )
        self._system_tasks.append(
            asyncio.create_task(self._watchdog.run(), name="orchestrator_watchdog")
        )
        self._system_tasks.append(
            asyncio.create_task(self._emergency_listener(), name="orchestrator_emergency")
        )
        logger.info("orchestrator.started", workers=len(configs))

    async def stop(self) -> None:
        for worker in self._workers.values():
            worker.stop()
        if self._watchdog:
            self._watchdog.stop()
        all_tasks = list(self._tasks.values()) + self._system_tasks
        for t in all_tasks:
            t.cancel()
        await asyncio.gather(*all_tasks, return_exceptions=True)
        self._system_tasks.clear()
        logger.info("orchestrator.stopped", workers=len(self._workers))

    # ── Queries ───────────────────────────────────────────────────────────────

    def status(self) -> list[WorkerStatus]:
        return [w.status() for w in self._workers.values()]

    def worker_count(self) -> int:
        return len(self._workers)

    def active_count(self) -> int:
        return sum(1 for w in self._workers.values() if w.status().is_alive)

    def get_worker(self, symbol: str) -> CarryWorker | None:
        return self._workers.get(symbol)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _spawn(self, symbol: str) -> tuple[CarryWorker, asyncio.Task]:
        cfg = self._configs[symbol]
        worker = CarryWorker(
            config=cfg,
            bus=self._bus,
            hedge_engine=self._hedge_engine,
            risk_engine=self._risk_engine,
        )
        task = asyncio.create_task(worker.run(), name=f"worker_{symbol}")
        return worker, task

    async def _emergency_listener(self) -> None:
        q = self._bus.subscribe(f"emergency_stop.{list(self._configs.values())[0].exchange if self._configs else 'BYBIT'}")
        while True:
            alert = await q.get()
            logger.error("orchestrator.emergency_stop_received", reason=alert.reason)
            for worker in self._workers.values():
                worker.stop()
