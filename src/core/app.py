from __future__ import annotations

import asyncio
import signal
import sys

from src.core.container import ServiceContainer
from src.core.logging_setup import get_logger

logger = get_logger(__name__)


class Application:
    def __init__(self, container: ServiceContainer) -> None:
        self._container = container
        self._stop_event = asyncio.Event()

    def _install_signal_handlers(self) -> None:
        if sys.platform == "win32":
            signal.signal(signal.SIGTERM, lambda *_: self._stop_event.set())
            signal.signal(signal.SIGINT, lambda *_: self._stop_event.set())
        else:
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGTERM, signal.SIGINT):
                loop.add_signal_handler(sig, self._stop_event.set)

    async def run(self) -> None:
        self._install_signal_handlers()

        logger.info("application.starting")
        try:
            await self._container.startup()
        except Exception:
            logger.exception("application.startup_failed")
            raise

        logger.info("application.started")
        await self._stop_event.wait()

        logger.info("application.stopping")
        try:
            await self._container.shutdown()
        except Exception:
            logger.exception("application.shutdown_error")
        logger.info("application.stopped")
