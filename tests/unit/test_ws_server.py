from __future__ import annotations

import asyncio
import json

import pytest

from src.api import serializers as ser
from src.basis.models import BasisSnapshot
from src.core.bus import MarketDataBus
from src.funding.models import FundingAnalysis
from src.models.market import Exchange
from src.risk.models import RiskAlert, RiskSnapshot
from src.api.ws_server import WebSocketServer


# ── Helpers ───────────────────────────────────────────────────────────────────

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
        current_rate=0.0001, predicted_rate=0.00012, ewma_rate=0.0001,
        mean_rate=0.0001, std_rate=0.00005, z_score=1.0, percentile=0.8,
        predicted_next=0.00012, ci_lower=0.00005, ci_upper=0.00015,
        regime="mildly_bullish", acceleration=0.0,
        is_accelerating=False, acceleration_direction="stable",
        is_extreme=False, rate_direction="longs_paying",
        extreme_streak=0, annualized_carry=0.1095,
        daily_carry=0.0003, ts_ms=1_000,
    )


def _risk_alert() -> RiskAlert:
    return RiskAlert(
        exchange=Exchange.BYBIT, level=1,
        reason="delta_exceeded", symbol="BTCUSDT",
        value=6_000.0, limit=5_000.0, ts_ms=1_000,
    )


def _risk_snapshot() -> RiskSnapshot:
    return RiskSnapshot(
        exchange=Exchange.BYBIT,
        total_exposure_usd=80_000.0,
        max_symbol_delta_usd=1_200.0,
        worst_symbol="BTCUSDT",
        drawdown_pct=0.01,
        risk_level=0,
        is_emergency=False,
        ts_ms=1_000,
    )


# ── Serializers ───────────────────────────────────────────────────────────────

def test_basis_msg_structure():
    msg = json.loads(ser.basis_msg("BYBIT", "BTCUSDT", _basis()))
    assert msg["type"] == "basis"
    assert msg["exchange"] == "BYBIT"
    assert msg["symbol"] == "BTCUSDT"
    assert msg["data"]["basis_bps"] == pytest.approx(20.0)
    assert msg["data"]["spot_mid"] == pytest.approx(50_000.0)


def test_funding_msg_structure():
    msg = json.loads(ser.funding_msg("BYBIT", "BTCUSDT", _funding()))
    assert msg["type"] == "funding"
    assert msg["data"]["current_rate"] == pytest.approx(0.0001)
    assert msg["data"]["regime"] == "mildly_bullish"


def test_risk_alert_msg_structure():
    msg = json.loads(ser.risk_alert_msg("BYBIT", _risk_alert()))
    assert msg["type"] == "risk_alert"
    assert msg["data"]["level"] == 1
    assert msg["data"]["reason"] == "delta_exceeded"
    assert "symbol" not in msg  # no top-level symbol for portfolio alerts


def test_risk_snapshot_msg_structure():
    msg = json.loads(ser.risk_snapshot_msg("BYBIT", _risk_snapshot()))
    assert msg["type"] == "risk_snapshot"
    assert msg["data"]["drawdown_pct"] == pytest.approx(0.01)
    assert msg["data"]["total_exposure_usd"] == pytest.approx(80_000.0)


def test_workers_msg_structure():
    from src.strategy.models import WorkerStatus
    import time
    statuses = [
        WorkerStatus(symbol="BTCUSDT", state=3, heartbeat=time.time(),
                     periods_held=2, total_trades=1, restart_count=0, ts_ms=1_000),
    ]
    msg = json.loads(ser.workers_msg("BYBIT", statuses))
    assert msg["type"] == "workers"
    assert isinstance(msg["data"], list)
    assert msg["data"][0]["symbol"] == "BTCUSDT"
    assert msg["data"][0]["state"] == 3


def test_balance_msg_structure():
    msg = json.loads(ser.balance_msg("BYBIT", "USDT", 95_000.0, 100_000.0))
    assert msg["type"] == "balance"
    assert msg["data"]["currency"] == "USDT"
    assert msg["data"]["available"] == pytest.approx(95_000.0)


def test_equity_msg_structure():
    msg = json.loads(ser.equity_msg("BYBIT", 102_500.0))
    assert msg["type"] == "equity"
    assert msg["data"]["total_equity"] == pytest.approx(102_500.0)


def test_all_serializers_produce_valid_json():
    """Smoke test: none of the serializers should raise."""
    ser.basis_msg("BYBIT", "BTCUSDT", _basis())
    ser.funding_msg("BYBIT", "BTCUSDT", _funding())
    ser.risk_alert_msg("BYBIT", _risk_alert())
    ser.risk_snapshot_msg("BYBIT", _risk_snapshot())
    ser.balance_msg("BYBIT", "USDT", 1.0, 1.0)
    ser.equity_msg("BYBIT", 100_000.0)


# ── WebSocketServer broadcast logic ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_ws_server_starts_correct_number_of_tasks():
    bus = MarketDataBus()
    server = WebSocketServer(bus, "BYBIT", ["BTCUSDT", "ETHUSDT"], port=19999)

    await server.start()
    await asyncio.sleep(0.05)

    # 4 tasks per symbol (basis, funding, fill, liq) + 2 portfolio = 10
    assert len(server._tasks) == 10

    await server.stop()


@pytest.mark.asyncio
async def test_ws_server_stop_clears_tasks():
    bus = MarketDataBus()
    server = WebSocketServer(bus, "BYBIT", ["BTCUSDT"], port=19998)

    await server.start()
    await asyncio.sleep(0.01)
    await server.stop()

    assert server._tasks == []


@pytest.mark.asyncio
async def test_ws_server_broadcast_skips_dead_clients():
    """_broadcast should remove dead clients silently."""
    bus = MarketDataBus()
    server = WebSocketServer(bus, "BYBIT", [], port=19997)

    class DeadWS:
        async def send_str(self, _): raise ConnectionResetError()

    server._clients.add(DeadWS())  # type: ignore
    await server._broadcast('{"test": 1}')

    # Dead client should have been removed
    assert len(server._clients) == 0


@pytest.mark.asyncio
async def test_ws_server_broadcast_empty_clients_is_noop():
    bus = MarketDataBus()
    server = WebSocketServer(bus, "BYBIT", [], port=19996)
    # Should not raise even with empty client set
    await server._broadcast('{"ok": true}')


@pytest.mark.asyncio
async def test_ws_server_with_worker_status_poller():
    bus = MarketDataBus()
    calls = []

    def get_statuses():
        calls.append(1)
        return []

    server = WebSocketServer(bus, "BYBIT", [], port=19995,
                             get_worker_statuses=get_statuses)
    await server.start()
    await asyncio.sleep(0)

    # Poller task should be included
    task_names = [t.get_name() for t in server._tasks]
    assert "ws_poll_workers" in task_names

    await server.stop()
