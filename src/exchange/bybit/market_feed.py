from __future__ import annotations

from typing import Any

from src.core.bus import MarketDataBus
from src.core.config import ExchangeConfig
from src.core.logging_setup import get_logger
from src.exchange.base import ExchangeMarketFeed
from src.exchange.bybit import constants as C
from src.exchange.bybit.ob_handler import BybitOrderBookHandler
from src.exchange.bybit.parsers import parse_linear_ticker, parse_liquidation, parse_spot_ticker
from src.exchange.bybit.ws_client import BybitWSClient
from src.exchange.orderbook import OrderBookState
from src.models.market import InstrumentType

logger = get_logger(__name__)

_EXCHANGE_NAME = "BYBIT"


class BybitMarketFeed(ExchangeMarketFeed):
    """
    Manages two Bybit public WebSocket connections:
      /spot   — spot tickers + spot orderbooks
      /linear — perp tickers, funding, OI, liquidations, perp orderbooks

    All parsed data is published to MarketDataBus under typed topics.
    """

    def __init__(self, config: ExchangeConfig, bus: MarketDataBus) -> None:
        self._config = config
        self._bus = bus
        rc = config.reconnect
        base = config.ws_public_url

        self._spot_ws = BybitWSClient(
            url=base + C.SPOT_PATH,
            on_message=self._handle_spot,
            max_reconnect_attempts=rc.max_attempts,
            base_delay=rc.base_delay,
            max_delay=rc.max_delay,
            heartbeat_interval=C.HEARTBEAT_INTERVAL,
        )
        self._linear_ws = BybitWSClient(
            url=base + C.LINEAR_PATH,
            on_message=self._handle_linear,
            max_reconnect_attempts=rc.max_attempts,
            base_delay=rc.base_delay,
            max_delay=rc.max_delay,
            heartbeat_interval=C.HEARTBEAT_INTERVAL,
        )

        self._spot_ob = BybitOrderBookHandler(
            bus=bus,
            category="SPOT",
            instrument_type=InstrumentType.SPOT,
            on_resub=self._resub_spot_orderbook,
        )
        self._perp_ob = BybitOrderBookHandler(
            bus=bus,
            category="PERP",
            instrument_type=InstrumentType.PERPETUAL,
            on_resub=self._resub_perp_orderbook,
        )

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def start(self) -> None:
        await self._spot_ws.start()
        await self._linear_ws.start()
        logger.info("bybit_feed.started", testnet=self._config.testnet)

    async def stop(self) -> None:
        await self._spot_ws.stop()
        await self._linear_ws.stop()
        logger.info("bybit_feed.stopped")

    async def wait_ready(self, timeout: float = 10.0) -> bool:
        import asyncio
        spot_ok, linear_ok = await asyncio.gather(
            self._spot_ws.wait_connected(timeout),
            self._linear_ws.wait_connected(timeout),
        )
        return spot_ok and linear_ok

    # ── Subscriptions ──────────────────────────────────────────────────────────

    async def subscribe_spot_ticker(self, symbol: str) -> None:
        await self._spot_ws.subscribe([C.ticker_topic(symbol)])

    async def subscribe_perp_ticker(self, symbol: str) -> None:
        await self._linear_ws.subscribe([C.ticker_topic(symbol)])

    async def subscribe_spot_orderbook(self, symbol: str, depth: int = 50) -> None:
        await self._spot_ws.subscribe([C.orderbook_topic(symbol, depth)])

    async def subscribe_perp_orderbook(self, symbol: str, depth: int = 50) -> None:
        await self._linear_ws.subscribe([C.orderbook_topic(symbol, depth)])

    async def subscribe_liquidations(self, symbol: str) -> None:
        await self._linear_ws.subscribe([C.liquidation_topic(symbol)])

    def get_spot_book(self, symbol: str) -> OrderBookState | None:
        return self._spot_ob.get_book(symbol)

    def get_perp_book(self, symbol: str) -> OrderBookState | None:
        return self._perp_ob.get_book(symbol)

    # ── Re-subscribe callbacks (called by ob_handler on sequence gap) ──────────

    async def _resub_spot_orderbook(self, symbol: str, _category: str, depth: int) -> None:
        await self._spot_ws.resubscribe([C.orderbook_topic(symbol, depth)])

    async def _resub_perp_orderbook(self, symbol: str, _category: str, depth: int) -> None:
        await self._linear_ws.resubscribe([C.orderbook_topic(symbol, depth)])

    # ── Message handlers ───────────────────────────────────────────────────────

    async def _handle_spot(self, data: dict[str, Any]) -> None:
        topic: str = data.get("topic", "")
        ts_ms: int = data.get("ts", 0)

        if topic.startswith("tickers."):
            symbol = topic[8:]
            ticker = parse_spot_ticker(data, ts_ms)
            if ticker:
                self._bus.publish(C.bus_ticker_topic(_EXCHANGE_NAME, symbol, "SPOT"), ticker)

        elif topic.startswith("orderbook."):
            await self._spot_ob.handle(data, ts_ms)

    async def _handle_linear(self, data: dict[str, Any]) -> None:
        topic: str = data.get("topic", "")
        ts_ms: int = data.get("ts", 0)

        if topic.startswith("tickers."):
            symbol = topic[8:]
            ticker, funding, oi = parse_linear_ticker(data, ts_ms)
            if ticker:
                self._bus.publish(C.bus_ticker_topic(_EXCHANGE_NAME, symbol, "PERP"), ticker)
            if funding:
                self._bus.publish(C.bus_funding_topic(_EXCHANGE_NAME, symbol), funding)
            if oi:
                self._bus.publish(C.bus_oi_topic(_EXCHANGE_NAME, symbol), oi)

        elif topic.startswith("orderbook."):
            await self._perp_ob.handle(data, ts_ms)

        elif topic.startswith("liquidation."):
            symbol = topic[12:]
            event = parse_liquidation(data, ts_ms)
            if event:
                self._bus.publish(C.bus_liquidation_topic(_EXCHANGE_NAME, symbol), event)
