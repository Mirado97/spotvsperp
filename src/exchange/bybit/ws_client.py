from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import orjson

from src.core.logging_setup import get_logger

logger = get_logger(__name__)

_MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]

_WS_BATCH = 10  # Bybit max topics per subscribe message


def _chunks(lst: list[str], n: int) -> list[list[str]]:
    return [lst[i:i + n] for i in range(0, len(lst), n)]


class BybitWSClient:
    """
    Single authenticated-or-public WebSocket connection to one Bybit endpoint.

    Lifecycle:
      start() → background task that connects and reconnects forever
      subscribe() → adds topics; sends subscription if already connected
      stop()  → cancels background task, closes connection cleanly

    Reconnect uses exponential backoff with ±10% jitter to avoid thundering
    herd when the exchange drops many clients simultaneously.
    """

    def __init__(
        self,
        url: str,
        on_message: _MessageHandler,
        max_reconnect_attempts: int = 10,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        heartbeat_interval: float = 20.0,
    ) -> None:
        self._url = url
        self._on_message = on_message
        self._max_attempts = max_reconnect_attempts
        self._base_delay = base_delay
        self._max_delay = max_delay
        self._heartbeat_interval = heartbeat_interval

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._subscribed_topics: list[str] = []
        self._running = False
        self._connected = asyncio.Event()
        self._run_task: asyncio.Task[None] | None = None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        self._running = True
        self._session = aiohttp.ClientSession()
        self._run_task = asyncio.create_task(
            self._run_with_reconnect(), name=f"ws:{self._url.split('/')[-1]}"
        )

    async def stop(self) -> None:
        self._running = False
        if self._run_task:
            self._run_task.cancel()
            await asyncio.gather(self._run_task, return_exceptions=True)
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("ws_client.stopped", url=self._url)

    async def subscribe(self, topics: list[str]) -> None:
        new = [t for t in topics if t not in self._subscribed_topics]
        if not new:
            return
        self._subscribed_topics.extend(new)
        if self._connected.is_set():
            for chunk in _chunks(new, _WS_BATCH):
                await self._send({"op": "subscribe", "args": chunk})

    async def resubscribe(self, topics: list[str]) -> None:
        """Force a re-subscription (sends subscribe even if already tracked).
        Bybit responds to a duplicate subscribe with a fresh snapshot."""
        if self._connected.is_set():
            await self._send({"op": "subscribe", "args": topics})

    async def wait_connected(self, timeout: float = 10.0) -> bool:
        try:
            await asyncio.wait_for(self._connected.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _run_with_reconnect(self) -> None:
        attempts = 0
        while self._running:
            try:
                await self._connect_and_run()
                attempts = 0
            except asyncio.CancelledError:
                return
            except Exception as exc:
                attempts += 1
                if attempts > self._max_attempts:
                    logger.error(
                        "ws_client.max_reconnects_exceeded",
                        url=self._url,
                        attempts=attempts,
                    )
                    return

                raw_delay = min(self._base_delay * (2 ** (attempts - 1)), self._max_delay)
                jitter = raw_delay * 0.1 * (2 * random.random() - 1)
                delay = raw_delay + jitter

                logger.warning(
                    "ws_client.reconnecting",
                    url=self._url,
                    attempt=attempts,
                    delay_s=round(delay, 2),
                    error=str(exc),
                )
                self._connected.clear()
                await asyncio.sleep(delay)

    async def _connect_and_run(self) -> None:
        assert self._session is not None
        async with self._session.ws_connect(self._url) as ws:
            self._ws = ws
            self._connected.set()
            logger.info("ws_client.connected", url=self._url)

            if self._subscribed_topics:
                # Liquidations in a separate batch; all batches capped at _WS_BATCH topics
                primary = [t for t in self._subscribed_topics if not t.startswith("liquidation.")]
                secondary = [t for t in self._subscribed_topics if t.startswith("liquidation.")]
                for chunk in _chunks(primary, _WS_BATCH):
                    logger.info("ws_client.subscribing", url=self._url, count=len(chunk))
                    await self._send({"op": "subscribe", "args": chunk})
                for chunk in _chunks(secondary, _WS_BATCH):
                    logger.info("ws_client.subscribing", url=self._url, count=len(chunk))
                    await self._send({"op": "subscribe", "args": chunk})

            hb_task = asyncio.create_task(self._heartbeat_loop(), name="ws_heartbeat")
            try:
                await self._receive_loop(ws)
            finally:
                hb_task.cancel()
                await asyncio.gather(hb_task, return_exceptions=True)

        self._connected.clear()

    async def _receive_loop(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                await self._dispatch(msg.data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                await self._dispatch(msg.data)
            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error("ws_client.error", url=self._url, exc=str(ws.exception()))
                return
            elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSING):
                logger.info("ws_client.server_close", url=self._url, code=ws.close_code)
                return

    async def _dispatch(self, raw: str | bytes) -> None:
        try:
            data: dict[str, Any] = orjson.loads(raw)
        except Exception:
            logger.warning("ws_client.json_parse_error", raw=str(raw)[:200])
            return

        # Log subscription confirmations and errors from Bybit
        if "topic" not in data:
            if data.get("op") or data.get("success") is not None:
                logger.info("ws_client.op_response", url=self._url.split("/")[-1],
                            success=data.get("success"), op=data.get("op"),
                            ret_msg=data.get("ret_msg", ""))
            return

        logger.debug("ws_client.topic_received", topic=data.get("topic"), url=self._url.split("/")[-1])

        try:
            await self._on_message(data)
        except Exception:
            logger.exception("ws_client.handler_error", topic=data.get("topic"))

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(self._heartbeat_interval)
            await self._send({"op": "ping"})

    async def _send(self, payload: dict[str, Any]) -> None:
        if self._ws and not self._ws.closed:
            try:
                await self._ws.send_bytes(orjson.dumps(payload))
            except Exception:
                pass  # connection drop will be caught by receive loop
