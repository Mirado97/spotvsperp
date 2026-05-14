"""
Live integration example: stream BTC + ETH spot/perp tickers from Bybit testnet.

Prerequisites:
  1. Copy .env.example to .env and fill in BYBIT_API_KEY / BYBIT_API_SECRET
  2. Activate venv: .venv/Scripts/activate  (Windows)
  3. Run: python examples/bybit_market_feed.py

Press Ctrl+C to stop.
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from src.core.bus import MarketDataBus
from src.core.config import load_settings
from src.core.logging_setup import configure_logging, get_logger
from src.exchange.bybit.market_feed import BybitMarketFeed
from src.models.funding import FundingRate
from src.models.market import Ticker

logger = get_logger(__name__)

SYMBOLS = ["BTCUSDT", "ETHUSDT"]


async def print_stream(name: str, q: asyncio.Queue) -> None:
    while True:
        item = await q.get()
        if isinstance(item, Ticker):
            logger.info(
                name,
                symbol=item.symbol,
                bid=item.bid,
                ask=item.ask,
                spread_bps=round(item.spread_bps, 3),
            )
        elif isinstance(item, FundingRate):
            logger.info(
                name,
                symbol=item.symbol,
                rate=item.rate,
                predicted=item.predicted,
                annualized_pct=round(item.annualized * 100, 4),
                regime=("extreme" if item.is_extreme else "normal"),
            )
        else:
            logger.info(name, raw=str(item)[:200])


async def main() -> None:
    configure_logging(level="INFO", fmt="console")
    settings = load_settings("development")
    bybit_cfg = settings.exchanges.bybit
    assert bybit_cfg, "Bybit not configured in config/base.yaml"

    bus = MarketDataBus()
    feed = BybitMarketFeed(config=bybit_cfg, bus=bus)

    await feed.start()

    logger.info("waiting_for_connection")
    connected = await feed.wait_ready(timeout=10.0)
    if not connected:
        logger.error("connection_timeout")
        await feed.stop()
        return

    # Subscribe to spot + perp for each symbol
    for sym in SYMBOLS:
        await feed.subscribe_spot_ticker(sym)
        await feed.subscribe_perp_ticker(sym)
        await feed.subscribe_liquidations(sym)

    # Build queues
    queues = {
        f"spot:{sym}": bus.subscribe(f"ticker.BYBIT.{sym}.SPOT")
        for sym in SYMBOLS
    } | {
        f"perp:{sym}": bus.subscribe(f"ticker.BYBIT.{sym}.PERP")
        for sym in SYMBOLS
    } | {
        f"funding:{sym}": bus.subscribe(f"funding.BYBIT.{sym}")
        for sym in SYMBOLS
    }

    logger.info("streaming.live", symbols=SYMBOLS)

    tasks = [
        asyncio.create_task(print_stream(name, q))
        for name, q in queues.items()
    ]

    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        pass
    finally:
        for t in tasks:
            t.cancel()
        await feed.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped.")
