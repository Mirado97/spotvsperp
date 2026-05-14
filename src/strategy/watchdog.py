from __future__ import annotations

import asyncio
import time
from typing import Callable

from src.core.logging_setup import get_logger
from src.strategy.carry_worker import CarryWorker
from src.strategy.models import WorkerState

logger = get_logger(__name__)


class WorkerWatchdog:
    """
    Monitors CarryWorker health via heartbeat and task completion.

    Checks every `check_interval_s` seconds:
      - If the asyncio.Task is done (crashed/finished): restart unless max_restarts exceeded.
      - If the worker hasn't updated its heartbeat for >heartbeat_timeout_s: cancel + restart.

    The factory_fn creates a fresh (worker, task) pair for a given symbol.
    """

    def __init__(
        self,
        workers: dict[str, CarryWorker],
        tasks: dict[str, asyncio.Task],
        factory_fn: Callable[[str], tuple[CarryWorker, asyncio.Task]],
        heartbeat_timeout_s: float = 30.0,
        max_restarts: int = 3,
        check_interval_s: float = 10.0,
    ) -> None:
        self._workers = workers
        self._tasks = tasks
        self._factory = factory_fn
        self._timeout = heartbeat_timeout_s
        self._max_restarts = max_restarts
        self._interval = check_interval_s
        self._restart_counts: dict[str, int] = {}
        self._stop_event = asyncio.Event()

    # ── Public API ────────────────────────────────────────────────────────────

    async def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
                break  # stop_event set
            except asyncio.TimeoutError:
                pass
            self._check_all()

    def stop(self) -> None:
        self._stop_event.set()

    def restart_count(self, symbol: str) -> int:
        return self._restart_counts.get(symbol, 0)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check_all(self) -> None:
        now = time.time()
        for sym in list(self._workers.keys()):
            task = self._tasks.get(sym)
            worker = self._workers.get(sym)
            if task is None or worker is None:
                continue

            if task.done():
                exc = None
                if not task.cancelled():
                    try:
                        exc = task.exception()
                    except Exception:
                        pass
                logger.warning("watchdog.task_done", symbol=sym, exc=str(exc) if exc else None)
                self._restart(sym)
            elif now - worker.heartbeat > self._timeout:
                logger.warning("watchdog.stuck", symbol=sym, elapsed=now - worker.heartbeat)
                task.cancel()
                self._restart(sym)

    def _restart(self, symbol: str) -> None:
        count = self._restart_counts.get(symbol, 0)
        if count >= self._max_restarts:
            logger.error("watchdog.max_restarts_reached", symbol=symbol)
            w = self._workers.get(symbol)
            if w:
                w.fail()
            return

        self._restart_counts[symbol] = count + 1
        logger.warning("watchdog.restarting", symbol=symbol, attempt=count + 1)

        new_worker, new_task = self._factory(symbol)
        self._workers[symbol] = new_worker
        self._tasks[symbol] = new_task
