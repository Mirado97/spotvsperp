from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.basis.models import BasisSnapshot
from src.core.bus import MarketDataBus
from src.funding.models import FundingAnalysis
from src.models.liquidation import LiquidationEvent
from src.models.market import Exchange
from src.models.orders import Fill, OrderSide
from src.models.orders import InstrumentType
from src.storage.redis_client import RedisClient
from src.storage.repositories import (
    BalanceRepository,
    MarketRepository,
    MetricsRepository,
    PositionRepository,
    TradeRepository,
)
from src.storage.writer import StorageWriter


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_pool():
    pool = MagicMock()
    pool.execute = AsyncMock(return_value="INSERT 0 1")
    pool.fetchval = AsyncMock(return_value=1)
    pool.fetchrow = AsyncMock(return_value=None)
    pool.fetch = AsyncMock(return_value=[])
    return pool


def _mock_redis():
    r = MagicMock()
    r.set = AsyncMock()
    r.setex = AsyncMock()
    r.get = AsyncMock(return_value=None)
    r.delete = AsyncMock()
    r.publish = AsyncMock(return_value=1)
    r.ping = AsyncMock()
    r.aclose = AsyncMock()
    return r


def _basis() -> BasisSnapshot:
    return BasisSnapshot(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        spot_mid=50_000.0, perp_mid=50_100.0,
        basis=0.002, basis_bps=20.0,
        annualized_basis=2.19,
        perp_premium=100.0,
        funding_rate=0.0001, predicted_funding=0.0001,
        funding_yield_ann=0.1095,
        ts_ms=1_000,
    )


def _funding() -> FundingAnalysis:
    return FundingAnalysis(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        current_rate=0.0001, predicted_rate=0.0001, ewma_rate=0.0001,
        mean_rate=0.0001, std_rate=0.00005, z_score=1.0, percentile=0.8,
        predicted_next=0.0001, ci_lower=0.00005, ci_upper=0.00015,
        regime="mildly_bullish", acceleration=0.0,
        is_accelerating=False, acceleration_direction="stable",
        is_extreme=False, rate_direction="longs_paying",
        extreme_streak=0, annualized_carry=0.1095,
        daily_carry=0.0003, ts_ms=1_000,
    )


def _liq() -> LiquidationEvent:
    return LiquidationEvent(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        side="long", qty=0.5, price=50_000.0, value_usd=25_000.0, ts_ms=1_000,
    )


# ── TradeRepository ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_trade_repo_insert_trade_calls_fetchval():
    import datetime
    pool = _mock_pool()
    repo = TradeRepository(pool)
    result = await repo.insert_trade(
        strategy_id="s1", exchange="BYBIT", symbol="BTCUSDT",
        side="long_carry", qty=0.01,
        spot_entry=50_000.0, perp_entry=50_100.0, entry_basis=0.002,
        opened_at=datetime.datetime.utcnow(),
    )
    assert pool.fetchval.called
    assert result == 1


@pytest.mark.asyncio
async def test_trade_repo_close_trade_calls_execute():
    pool = _mock_pool()
    repo = TradeRepository(pool)
    await repo.close_trade(
        trade_id=1, spot_exit=51_000.0, perp_exit=51_050.0,
        exit_basis=0.001, realized_pnl=10.0, realized_basis=0.001,
    )
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "UPDATE trades" in sql
    assert "status='closed'" in sql


@pytest.mark.asyncio
async def test_trade_repo_insert_fill():
    pool = _mock_pool()
    repo = TradeRepository(pool)
    fill = Fill(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        order_id="cid1", fill_id="eid1",
        side=OrderSide.BUY,
        qty=0.01, price=50_000.0,
        fee=0.05, fee_currency="USDT",
        ts_ms=1_000,
    )
    await repo.insert_fill(fill, strategy_id="s1")
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "INSERT INTO fills" in sql


@pytest.mark.asyncio
async def test_trade_repo_get_open_trades():
    pool = _mock_pool()
    repo = TradeRepository(pool)
    result = await repo.get_open_trades("BYBIT", "BTCUSDT")
    assert pool.fetch.called
    assert result == []


# ── PositionRepository ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_position_repo_upsert():
    pool = _mock_pool()
    repo = PositionRepository(pool)
    await repo.upsert("BYBIT", "BTCUSDT", 0.01, -0.01, 50_000.0, 50_100.0, 0.0)
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "ON CONFLICT" in sql
    assert "positions" in sql


@pytest.mark.asyncio
async def test_position_repo_get():
    pool = _mock_pool()
    repo = PositionRepository(pool)
    result = await repo.get("BYBIT", "BTCUSDT")
    assert pool.fetchrow.called
    assert result is None


@pytest.mark.asyncio
async def test_position_repo_get_all():
    pool = _mock_pool()
    repo = PositionRepository(pool)
    result = await repo.get_all()
    assert pool.fetch.called
    assert result == []


# ── MarketRepository ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_market_repo_insert_basis():
    pool = _mock_pool()
    repo = MarketRepository(pool)
    await repo.insert_basis(_basis())
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "basis_history" in sql


@pytest.mark.asyncio
async def test_market_repo_insert_funding():
    pool = _mock_pool()
    repo = MarketRepository(pool)
    await repo.insert_funding(_funding())
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "INSERT INTO funding" in sql


@pytest.mark.asyncio
async def test_market_repo_insert_liquidation():
    pool = _mock_pool()
    repo = MarketRepository(pool)
    await repo.insert_liquidation(_liq())
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "liquidation_events" in sql


@pytest.mark.asyncio
async def test_market_repo_insert_spread():
    pool = _mock_pool()
    repo = MarketRepository(pool)
    await repo.insert_spread("BYBIT", "BTCUSDT", "spot", 49_990.0, 50_010.0, 4.0, 1_000)
    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "spreads" in sql


# ── BalanceRepository ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_balance_repo_upsert():
    pool = _mock_pool()
    repo = BalanceRepository(pool)
    await repo.upsert("BYBIT", "USDT", 95_000.0, 100_000.0)
    sql = pool.execute.call_args[0][0]
    assert "ON CONFLICT" in sql
    assert "balances" in sql


@pytest.mark.asyncio
async def test_balance_repo_insert_pnl():
    pool = _mock_pool()
    repo = BalanceRepository(pool)
    await repo.insert_pnl("BYBIT", total_equity=101_000.0, realized_pnl=1_000.0)
    sql = pool.execute.call_args[0][0]
    assert "pnl_history" in sql


# ── MetricsRepository ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_metrics_repo_insert_latency():
    pool = _mock_pool()
    repo = MetricsRepository(pool)
    await repo.insert_latency("place_order", "BYBIT", 12.5, "BTCUSDT")
    sql = pool.execute.call_args[0][0]
    assert "latency_metrics" in sql


# ── RedisClient ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_redis_cache_json_with_ttl():
    client = RedisClient.__new__(RedisClient)
    client._redis = _mock_redis()
    await client.cache_json("key1", {"foo": 42}, ttl_s=30)
    client._redis.setex.assert_called_once_with("key1", 30, json.dumps({"foo": 42}))


@pytest.mark.asyncio
async def test_redis_get_json_returns_none_on_miss():
    client = RedisClient.__new__(RedisClient)
    client._redis = _mock_redis()
    client._redis.get = AsyncMock(return_value=None)
    result = await client.get_json("missing")
    assert result is None


@pytest.mark.asyncio
async def test_redis_get_json_deserializes():
    client = RedisClient.__new__(RedisClient)
    client._redis = _mock_redis()
    client._redis.get = AsyncMock(return_value='{"val": 1}')
    result = await client.get_json("key")
    assert result == {"val": 1}


@pytest.mark.asyncio
async def test_redis_cache_basis_uses_correct_key():
    client = RedisClient.__new__(RedisClient)
    client._redis = _mock_redis()
    await client.cache_basis("BYBIT", "BTCUSDT", {"basis_bps": 20.0})
    key = client._redis.setex.call_args[0][0]
    assert key == "basis:BYBIT:BTCUSDT"


@pytest.mark.asyncio
async def test_redis_cache_position_uses_correct_key():
    client = RedisClient.__new__(RedisClient)
    client._redis = _mock_redis()
    await client.cache_position("BYBIT", "BTCUSDT", {"spot_qty": 0.01})
    key = client._redis.setex.call_args[0][0]
    assert key == "pos:BYBIT:BTCUSDT"


# ── StorageWriter ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_storage_writer_persists_basis():
    bus = MarketDataBus()
    pool = _mock_pool()
    market_repo = MarketRepository(pool)
    redis_client = RedisClient.__new__(RedisClient)
    redis_client._redis = _mock_redis()

    writer = StorageWriter(bus, market_repo, redis_client, "BYBIT", ["BTCUSDT"])
    writer.start()
    await asyncio.sleep(0)

    bus.publish("basis.BYBIT.BTCUSDT", _basis())
    await asyncio.sleep(0.05)

    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "basis_history" in sql

    writer.stop()


@pytest.mark.asyncio
async def test_storage_writer_persists_funding():
    bus = MarketDataBus()
    pool = _mock_pool()
    market_repo = MarketRepository(pool)
    redis_client = RedisClient.__new__(RedisClient)
    redis_client._redis = _mock_redis()

    writer = StorageWriter(bus, market_repo, redis_client, "BYBIT", ["BTCUSDT"])
    writer.start()
    await asyncio.sleep(0)

    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding())
    await asyncio.sleep(0.05)

    assert pool.execute.called
    sql = pool.execute.call_args[0][0]
    assert "funding" in sql

    writer.stop()


@pytest.mark.asyncio
async def test_storage_writer_stop_cancels_tasks():
    bus = MarketDataBus()
    pool = _mock_pool()
    market_repo = MarketRepository(pool)
    redis_client = RedisClient.__new__(RedisClient)
    redis_client._redis = _mock_redis()

    writer = StorageWriter(bus, market_repo, redis_client, "BYBIT", ["BTCUSDT"])
    writer.start()
    await asyncio.sleep(0)

    assert len(writer._tasks) == 3  # 3 tasks per symbol (basis, funding, liq)
    writer.stop()
    assert writer._tasks == []     # cleared after stop


@pytest.mark.asyncio
async def test_storage_writer_multiple_symbols():
    bus = MarketDataBus()
    pool = _mock_pool()
    market_repo = MarketRepository(pool)
    redis_client = RedisClient.__new__(RedisClient)
    redis_client._redis = _mock_redis()

    writer = StorageWriter(
        bus, market_repo, redis_client, "BYBIT", ["BTCUSDT", "ETHUSDT"]
    )
    writer.start()
    await asyncio.sleep(0)

    # 3 tasks per symbol (basis, funding, liq)
    assert len(writer._tasks) == 6

    writer.stop()
