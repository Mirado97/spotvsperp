from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

import aiohttp
from aiohttp import web

from src.core.bus import MarketDataBus
from src.core.logging_setup import get_logger
from src.api import serializers as ser

logger = get_logger(__name__)


class WebSocketServer:
    """
    Bridges the internal MarketDataBus to browser WebSocket clients.

    Subscribes to bus topics for each symbol and broadcasts JSON messages
    to all connected frontend clients. Supports auto-reconnect on the client side.

    Message envelope:
        {"type": str, "exchange": str, "symbol"?: str, "data": {...}}

    Types published: basis | funding | risk_alert | risk_snapshot |
                     fill | liq_alert | workers | balance | equity
    """

    def __init__(
        self,
        bus: MarketDataBus,
        exchange: str = "BYBIT",
        symbols: list[str] | None = None,
        host: str = "0.0.0.0",
        port: int = 8080,
        get_worker_statuses: Callable[[], list[Any]] | None = None,
        get_balance: Callable[[], Any] | None = None,
    ) -> None:
        self._bus = bus
        self._exchange = exchange
        self._symbols: list[str] = symbols or []
        self._host = host
        self._port = port
        self._get_statuses = get_worker_statuses
        self._get_balance = get_balance
        self._clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/health", self._health_handler)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self._host, self._port)
        await site.start()

        for sym in self._symbols:
            self._tasks += [
                asyncio.create_task(self._consume_basis(sym),   name=f"ws_basis_{sym}"),
                asyncio.create_task(self._consume_funding(sym), name=f"ws_funding_{sym}"),
                asyncio.create_task(self._consume_fill(sym),    name=f"ws_fill_{sym}"),
                asyncio.create_task(self._consume_liq(sym),     name=f"ws_liq_{sym}"),
            ]
        self._tasks += [
            asyncio.create_task(self._consume_risk_alerts(),    name="ws_risk_alerts"),
            asyncio.create_task(self._consume_risk_snapshots(), name="ws_risk_snapshots"),
            asyncio.create_task(self._consume_latency(),        name="ws_latency"),
        ]
        if self._get_statuses:
            self._tasks.append(
                asyncio.create_task(self._poll_workers(), name="ws_poll_workers")
            )
        if self._get_balance:
            self._tasks.append(
                asyncio.create_task(self._poll_balance(), name="ws_poll_balance")
            )
        logger.info("ws_server.started", host=self._host, port=self._port)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()
        if self._runner:
            await self._runner.cleanup()
        logger.info("ws_server.stopped")

    # ── WebSocket handler ─────────────────────────────────────────────────────

    async def _handle_ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        self._clients.add(ws)
        logger.info("ws.client_connected", peer=str(request.remote),
                    total=len(self._clients))
        try:
            async for _ in ws:
                pass  # client messages not processed in this version
        finally:
            self._clients.discard(ws)
            logger.info("ws.client_disconnected", remaining=len(self._clients))
        return ws

    @staticmethod
    async def _health_handler(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok"})

    # ── Broadcast helper ──────────────────────────────────────────────────────

    async def _broadcast(self, msg: str) -> None:
        if not self._clients:
            return
        dead: set[web.WebSocketResponse] = set()
        for ws in list(self._clients):
            try:
                await ws.send_str(msg)
            except (ConnectionResetError, aiohttp.ClientConnectionResetError):
                dead.add(ws)
            except Exception:
                dead.add(ws)
        self._clients -= dead

    # ── Per-symbol consumers ──────────────────────────────────────────────────

    async def _consume_basis(self, symbol: str) -> None:
        q = self._bus.subscribe(f"basis.{self._exchange}.{symbol}")
        while True:
            snap = await q.get()
            await self._broadcast(ser.basis_msg(self._exchange, symbol, snap))

    async def _consume_funding(self, symbol: str) -> None:
        q = self._bus.subscribe(f"funding_analysis.{self._exchange}.{symbol}")
        while True:
            analysis = await q.get()
            await self._broadcast(ser.funding_msg(self._exchange, symbol, analysis))

    async def _consume_fill(self, symbol: str) -> None:
        q = self._bus.subscribe(f"fill.{self._exchange}.{symbol}")
        while True:
            fill = await q.get()
            await self._broadcast(ser.fill_msg(self._exchange, symbol, fill))

    async def _consume_liq(self, symbol: str) -> None:
        q = self._bus.subscribe(f"liq_alert.{self._exchange}.{symbol}")
        while True:
            alert = await q.get()
            await self._broadcast(ser.liq_alert_msg(self._exchange, symbol, alert))

    # ── Portfolio consumers ───────────────────────────────────────────────────

    async def _consume_risk_alerts(self) -> None:
        q = self._bus.subscribe(f"risk_alert.{self._exchange}")
        while True:
            alert = await q.get()
            await self._broadcast(ser.risk_alert_msg(self._exchange, alert))

    async def _consume_risk_snapshots(self) -> None:
        q = self._bus.subscribe(f"risk_snapshot.{self._exchange}")
        while True:
            snap = await q.get()
            await self._broadcast(ser.risk_snapshot_msg(self._exchange, snap))

    async def _consume_latency(self) -> None:
        q = self._bus.subscribe(f"latency.{self._exchange}")
        while True:
            rest_rtt_ms = await q.get()
            if self._clients:
                await self._broadcast(ser.latency_msg(self._exchange, rest_rtt_ms))

    async def _poll_workers(self) -> None:
        while True:
            await asyncio.sleep(5.0)
            if self._clients:
                statuses = self._get_statuses()
                if statuses:
                    await self._broadcast(ser.workers_msg(self._exchange, statuses))

    async def _poll_balance(self) -> None:
        while True:
            if self._clients:
                try:
                    available, total = await self._get_balance()
                    await self._broadcast(
                        ser.balance_msg(self._exchange, "USDT", available, total)
                    )
                    await self._broadcast(ser.equity_msg(self._exchange, total))
                except Exception:
                    logger.exception("ws_server.balance_poll_error")
            await asyncio.sleep(30.0)
