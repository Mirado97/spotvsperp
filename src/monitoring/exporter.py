from __future__ import annotations

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from src.core.logging_setup import get_logger

logger = get_logger(__name__)


async def _metrics_handler(request: web.Request) -> web.Response:
    output = generate_latest()
    return web.Response(body=output, content_type=CONTENT_TYPE_LATEST)


class MetricsExporter:
    """
    Serves Prometheus metrics over HTTP at GET /metrics.

    Usage:
        exporter = MetricsExporter(port=9090)
        await exporter.start()
        # ... run app ...
        await exporter.stop()
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9090) -> None:
        self._host = host
        self._port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/metrics", _metrics_handler)
        app.router.add_get("/health", self._health_handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()
        logger.info("metrics_exporter.started", host=self._host, port=self._port)

    async def stop(self) -> None:
        if self._runner:
            await self._runner.cleanup()
            logger.info("metrics_exporter.stopped")

    @staticmethod
    async def _health_handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})
