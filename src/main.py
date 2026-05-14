"""Production entrypoint for the CEXvsCEX basis trading terminal."""
from __future__ import annotations

import asyncio
import os

from src.basis.engine import BasisEngine
from src.core.app import Application
from src.core.bus import MarketDataBus
from src.core.config import load_settings
from src.core.logging_setup import get_logger
from src.exchange.bybit.market_feed import BybitMarketFeed
from src.exchange.bybit.rest_client import BybitRestClient
from src.execution.bybit_executor import BybitExecutor
from src.execution.hedge_engine import HedgeEngine
from src.execution.order_tracker import OrderTracker
from src.funding.engine import FundingEngine
from src.liquidation.engine import LiquidationEngine
from src.monitoring.manager import MonitoringManager
from src.api.manager import APIManager
from src.risk.engine import RiskEngine
from src.risk.models import RiskLimits
from src.secrets.vault import SecretsVault
from src.storage.manager import StorageManager
from src.storage.writer import StorageWriter
from src.strategy.models import StrategyConfig
from src.strategy.orchestrator import StrategyOrchestrator

logger = get_logger(__name__)

_SYMBOLS = os.getenv("TRADING_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
_EXCHANGE = "BYBIT"


async def _build_app() -> Application:
    settings = load_settings()
    vault = SecretsVault()
    creds = vault.get_exchange_credentials(_EXCHANGE)

    postgres_dsn = vault.get(
        "POSTGRES_DSN",
        "postgresql://cex:cex@localhost:5432/cexvscex",
    )
    redis_url = vault.get("REDIS_URL", "redis://localhost:6379/0")

    bus = MarketDataBus()

    # ── Storage ───────────────────────────────────────────────────────────────
    storage = StorageManager(postgres_dsn, redis_url)
    await storage.connect()
    await storage.apply_schema()

    # ── Market feed ───────────────────────────────────────────────────────────
    exchange_cfg = settings.exchanges.bybit
    feed = BybitMarketFeed(exchange_cfg, bus)

    # ── Analysis engines ──────────────────────────────────────────────────────
    basis_engine = BasisEngine(bus, exchange=_EXCHANGE)
    funding_engine = FundingEngine(bus, exchange=_EXCHANGE)
    liq_engine = LiquidationEngine(bus, exchange=_EXCHANGE)

    # ── Execution ─────────────────────────────────────────────────────────────
    rest = BybitRestClient(
        api_key=creds.api_key,
        api_secret=creds.api_secret,
        testnet=creds.testnet,
    )
    tracker = OrderTracker()
    executor = BybitExecutor(rest, tracker)
    hedge_engine = HedgeEngine(executor, tracker)

    # ── Risk ──────────────────────────────────────────────────────────────────
    risk_limits = RiskLimits(
        max_position_usd=settings.risk.max_position_usd,
        max_total_exposure_usd=settings.risk.max_total_exposure_usd,
        max_exchange_exposure_usd=settings.risk.max_exchange_exposure_usd,
    )
    risk_engine = RiskEngine(
        bus=bus,
        limits=risk_limits,
        initial_equity=float(vault.get("INITIAL_EQUITY", "100000")),
    )

    # ── Strategy ──────────────────────────────────────────────────────────────
    strategy_configs = [
        StrategyConfig(symbol=sym, exchange=_EXCHANGE) for sym in _SYMBOLS
    ]
    orchestrator = StrategyOrchestrator(
        bus=bus,
        hedge_engine=hedge_engine,
        risk_engine=risk_engine,
    )

    # ── Storage writer ────────────────────────────────────────────────────────
    writer = StorageWriter(
        bus=bus,
        market_repo=storage.market,
        redis=storage.redis,
        exchange=_EXCHANGE,
        symbols=_SYMBOLS,
    )

    # ── Monitoring ────────────────────────────────────────────────────────────
    monitoring = MonitoringManager(
        bus=bus,
        exchange=_EXCHANGE,
        symbols=_SYMBOLS,
        exporter_port=settings.monitoring.metrics_port,
    )

    # ── API / WebSocket ───────────────────────────────────────────────────────
    api = APIManager(
        bus=bus,
        exchange=_EXCHANGE,
        symbols=_SYMBOLS,
        port=int(vault.get("WS_PORT", "8080")),
        get_worker_statuses=orchestrator.status,
    )

    # ── Lifecycle wiring ──────────────────────────────────────────────────────
    from src.core.container import ServiceContainer

    container = ServiceContainer()

    async def _startup() -> None:
        await monitoring.start()
        await feed.start()
        await basis_engine.start(_SYMBOLS)
        await funding_engine.start(_SYMBOLS)
        await liq_engine.start(_SYMBOLS)
        writer.start()
        await orchestrator.start(strategy_configs)
        await api.start()
        for sym in _SYMBOLS:
            await feed.subscribe_spot_ticker(sym)
            await feed.subscribe_perp_ticker(sym)
            await feed.subscribe_liquidations(sym)
        logger.info("app.all_services_started", symbols=_SYMBOLS)

    async def _shutdown() -> None:
        await api.stop()
        await orchestrator.stop()
        writer.stop()
        await liq_engine.stop()
        await funding_engine.stop()
        await basis_engine.stop()
        await feed.stop()
        await monitoring.stop()
        await storage.close()
        logger.info("app.all_services_stopped")

    container.on_startup(_startup)
    container.on_shutdown(_shutdown)

    return Application(container)


def main() -> None:
    try:
        import uvloop
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    except ImportError:
        pass

    async def _run() -> None:
        app = await _build_app()
        await app.run()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
