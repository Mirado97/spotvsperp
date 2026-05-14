"""Production entrypoint for the CEXvsCEX basis trading terminal."""
from __future__ import annotations

import asyncio
import os
import time

from src.basis.engine import BasisEngine
from src.core.logging_setup import configure_logging
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

_EXCHANGE = "BYBIT"


async def _resolve_symbols(rest: "BybitRestClient") -> list[str]:
    """Return symbol list: from env if set, else top-N by 24h volume from Bybit."""
    raw = os.getenv("TRADING_symbols", "").strip()
    if raw:
        return [s.strip() for s in raw.split(",") if s.strip()]
    n = int(os.getenv("TOP_symbols_N", "100"))
    symbols = await rest.get_top_usdt_perp_symbols(n)
    logger.info("symbols.auto_resolved", count=len(symbols), top5=symbols[:5])
    return symbols


async def _build_app() -> Application:
    settings = load_settings()
    configure_logging(level=os.getenv("APP_LOGGING__LEVEL", "DEBUG"), fmt="console")
    vault = SecretsVault()
    creds = vault.get_exchange_credentials(_EXCHANGE)

    postgres_dsn = vault.get(
        "POSTGRES_DSN",
        "postgresql://cex:cex@localhost:5432/cexvscex",
    )
    redis_url = vault.get("REDIS_URL", "redis://localhost:6379/0")

    bus = MarketDataBus()
    exchange_cfg = settings.exchanges.bybit

    # ── REST client (needed early for symbol resolution) ──────────────────────
    rest = BybitRestClient(
        api_key=creds.api_key,
        api_secret=creds.api_secret,
        testnet=creds.testnet,
        base_url=exchange_cfg.rest_url,
    )

    # ── Symbol list ───────────────────────────────────────────────────────────
    _symbols = await _resolve_symbols(rest)

    # ── Storage ───────────────────────────────────────────────────────────────
    storage = StorageManager(postgres_dsn, redis_url)
    await storage.connect()
    await storage.apply_schema()

    # ── Market feed ───────────────────────────────────────────────────────────
    feed = BybitMarketFeed(exchange_cfg, bus)

    # ── Analysis engines ──────────────────────────────────────────────────────
    basis_engine = BasisEngine(bus, exchange=_EXCHANGE)
    funding_engine = FundingEngine(bus, exchange=_EXCHANGE)
    liq_engine = LiquidationEngine(bus, exchange=_EXCHANGE)
    tracker = OrderTracker()
    executor = BybitExecutor(rest, tracker)
    hedge_engine = HedgeEngine(executor, tracker)

    # ── Risk ──────────────────────────────────────────────────────────────────
    risk_limits = RiskLimits(
        max_position_usd=settings.risk.max_position_usd,
        max_total_exposure_usd=settings.risk.max_total_exposure_usd,
    )
    risk_engine = RiskEngine(
        bus=bus,
        limits=risk_limits,
        initial_equity=float(vault.get("INITIAL_EQUITY", "100000")),
    )

    # ── Strategy ──────────────────────────────────────────────────────────────
    strategy_configs = [
        StrategyConfig(symbol=sym, exchange=_EXCHANGE) for sym in _symbols
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
        symbols=_symbols,
    )

    # ── Monitoring ────────────────────────────────────────────────────────────
    monitoring = MonitoringManager(
        bus=bus,
        exchange=_EXCHANGE,
        symbols=_symbols,
        exporter_port=settings.monitoring.metrics_port,
    )

    # ── API / WebSocket ───────────────────────────────────────────────────────
    async def _get_balance() -> tuple[float, float]:
        available = await rest.get_wallet_balance("USDT")
        return available, available

    api = APIManager(
        bus=bus,
        exchange=_EXCHANGE,
        symbols=_symbols,
        port=int(vault.get("WS_PORT", "8080")),
        get_worker_statuses=orchestrator.status,
        get_balance=_get_balance,
    )

    # ── Lifecycle wiring ──────────────────────────────────────────────────────
    from src.core.container import ServiceContainer

    container = ServiceContainer()
    _poller_task: asyncio.Task[None] | None = None

    async def _poll_rtt() -> None:
        """Measure REST round-trip latency — single request every 5s."""
        probe = _symbols[0] if _symbols else "BTCUSDT"
        while True:
            try:
                t0 = time.monotonic()
                await rest.get_linear_ticker(probe)
                bus.publish(f"latency.{_EXCHANGE}", int((time.monotonic() - t0) * 1000))
            except Exception:
                logger.exception("rtt_poller.error")
            await asyncio.sleep(5.0)

    async def _startup() -> None:
        nonlocal _poller_task
        await monitoring.start()
        await feed.start()
        await basis_engine.start(_symbols)
        await funding_engine.start(_symbols)
        await liq_engine.start(_symbols)
        writer.start()
        await orchestrator.start(strategy_configs)
        await api.start()
        await feed.subscribe_spot_tickers(_symbols)
        await feed.subscribe_perp_tickers(_symbols)
        await feed.subscribe_liquidations_batch(_symbols)
        _poller_task = asyncio.create_task(_poll_rtt(), name="rtt_poller")
        logger.info("app.all_services_started", symbols=_symbols)

    async def _shutdown() -> None:
        if _poller_task:
            _poller_task.cancel()
            await asyncio.gather(_poller_task, return_exceptions=True)
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
