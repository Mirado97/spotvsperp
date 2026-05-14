from __future__ import annotations

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.monitoring.collector import MetricsCollector
from src.monitoring.exporter import MetricsExporter

logger = get_logger(__name__)


class MonitoringManager:
    """
    Owns the MetricsCollector (bus subscriber) and MetricsExporter (HTTP server).

    Usage:
        mgr = MonitoringManager(bus, exchange="BYBIT", symbols=["BTCUSDT"],
                                exporter_port=9090)
        await mgr.start()
        # ... run app ...
        await mgr.stop()
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        symbols: list[str] | None = None,
        exporter_host: str = "0.0.0.0",
        exporter_port: int = 9090,
    ) -> None:
        self.collector = MetricsCollector(bus, exchange, symbols)
        self._exporter = MetricsExporter(exporter_host, exporter_port)

    async def start(self) -> None:
        self.collector.start()
        await self._exporter.start()
        logger.info("monitoring.started")

    async def stop(self) -> None:
        self.collector.stop()
        await self._exporter.stop()
        logger.info("monitoring.stopped")
