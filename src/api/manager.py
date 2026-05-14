from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.api.ws_server import WebSocketServer

logger = get_logger(__name__)


class APIManager:
    """
    Owns the WebSocketServer lifecycle.

    Usage:
        mgr = APIManager(bus, exchange="BYBIT", symbols=["BTCUSDT"],
                         get_worker_statuses=orchestrator.status)
        await mgr.start()
        # ... run app ...
        await mgr.stop()
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        symbols: list[str] | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        get_worker_statuses: Callable[[], list[Any]] | None = None,
    ) -> None:
        self._server = WebSocketServer(
            bus=bus,
            exchange=exchange,
            symbols=symbols,
            host=host,
            port=port,
            get_worker_statuses=get_worker_statuses,
        )

    @property
    def server(self) -> WebSocketServer:
        return self._server

    async def start(self) -> None:
        await self._server.start()
        logger.info("api.started")

    async def stop(self) -> None:
        await self._server.stop()
        logger.info("api.stopped")
