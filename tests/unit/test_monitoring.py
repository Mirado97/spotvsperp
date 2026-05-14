from __future__ import annotations

import asyncio

import pytest
from prometheus_client import REGISTRY

from src.basis.models import BasisSnapshot
from src.core.bus import MarketDataBus
from src.funding.models import FundingAnalysis
from src.models.market import Exchange
from src.monitoring.collector import MetricsCollector
from src.monitoring import metrics as m
from src.risk.models import RiskAlert, RiskSnapshot


# ── Helpers ───────────────────────────────────────────────────────────────────

def _basis(symbol: str = "BTCUSDT") -> BasisSnapshot:
    return BasisSnapshot(
        exchange=Exchange.BYBIT, symbol=symbol,
        spot_mid=50_000.0, perp_mid=50_100.0,
        basis=0.002, basis_bps=20.0,
        annualized_basis=2.19,
        perp_premium=100.0,
        funding_rate=0.0001, predicted_funding=0.0001,
        funding_yield_ann=0.1095,
        ts_ms=1_000,
    )


def _funding(symbol: str = "BTCUSDT", is_extreme: bool = False) -> FundingAnalysis:
    return FundingAnalysis(
        exchange=Exchange.BYBIT, symbol=symbol,
        current_rate=0.0001, predicted_rate=0.00012, ewma_rate=0.0001,
        mean_rate=0.0001, std_rate=0.00005, z_score=1.0, percentile=0.8,
        predicted_next=0.00012, ci_lower=0.00005, ci_upper=0.00015,
        regime="mildly_bullish", acceleration=0.0,
        is_accelerating=False, acceleration_direction="stable",
        is_extreme=is_extreme, rate_direction="longs_paying",
        extreme_streak=3 if is_extreme else 0,
        annualized_carry=0.1095, daily_carry=0.0003, ts_ms=1_000,
    )


def _risk_alert(level: int = 1, symbol: str = "BTCUSDT") -> RiskAlert:
    return RiskAlert(
        exchange=Exchange.BYBIT, level=level,
        reason="delta_exceeded", symbol=symbol,
        value=6_000.0, limit=5_000.0, ts_ms=1_000,
    )


def _risk_snapshot(drawdown: float = 0.02, exposure: float = 100_000.0) -> RiskSnapshot:
    return RiskSnapshot(
        exchange=Exchange.BYBIT,
        total_exposure_usd=exposure,
        max_symbol_delta_usd=1_000.0,
        worst_symbol="BTCUSDT",
        drawdown_pct=drawdown,
        risk_level=1,
        is_emergency=False,
        ts_ms=1_000,
    )


def _get_gauge(metric, *label_values: str) -> float:
    return metric.labels(*label_values)._value.get()


# ── Collector: basis metrics ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_updates_basis_bps():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    bus.publish("basis.BYBIT.BTCUSDT", _basis())
    await asyncio.sleep(0.05)

    assert _get_gauge(m.basis_bps, "BYBIT", "BTCUSDT") == pytest.approx(20.0)
    collector.stop()


@pytest.mark.asyncio
async def test_collector_updates_carry_score():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    snap = _basis()
    bus.publish("basis.BYBIT.BTCUSDT", snap)
    await asyncio.sleep(0.05)

    assert _get_gauge(m.carry_score, "BYBIT", "BTCUSDT") == pytest.approx(snap.carry_score)
    collector.stop()


# ── Collector: funding metrics ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_updates_funding_rate():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding())
    await asyncio.sleep(0.05)

    assert _get_gauge(m.funding_rate, "BYBIT", "BTCUSDT") == pytest.approx(0.0001)
    collector.stop()


@pytest.mark.asyncio
async def test_collector_sets_funding_extreme_flag():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding(is_extreme=True))
    await asyncio.sleep(0.05)

    assert _get_gauge(m.funding_is_extreme, "BYBIT", "BTCUSDT") == 1.0
    assert _get_gauge(m.funding_extreme_streak, "BYBIT", "BTCUSDT") == 3.0
    collector.stop()


@pytest.mark.asyncio
async def test_collector_clears_extreme_flag_when_normal():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding(is_extreme=True))
    await asyncio.sleep(0.05)
    bus.publish("funding_analysis.BYBIT.BTCUSDT", _funding(is_extreme=False))
    await asyncio.sleep(0.05)

    assert _get_gauge(m.funding_is_extreme, "BYBIT", "BTCUSDT") == 0.0
    collector.stop()


# ── Collector: risk metrics ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_updates_risk_level():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    bus.publish("risk_alert.BYBIT", _risk_alert(level=2))
    await asyncio.sleep(0.05)

    assert _get_gauge(m.risk_level, "BYBIT") == 2.0
    collector.stop()


@pytest.mark.asyncio
async def test_collector_updates_risk_snapshot():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)

    bus.publish("risk_snapshot.BYBIT", _risk_snapshot(drawdown=0.03, exposure=150_000.0))
    await asyncio.sleep(0.05)

    assert _get_gauge(m.drawdown_pct, "BYBIT") == pytest.approx(0.03)
    assert _get_gauge(m.total_exposure_usd, "BYBIT") == pytest.approx(150_000.0)
    collector.stop()


# ── Collector: direct update helpers ─────────────────────────────────────────

def test_record_worker_states_updates_active_count():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])

    from src.strategy.models import WorkerStatus
    import time

    statuses = [
        WorkerStatus(symbol="BTCUSDT", state=3, heartbeat=time.time(),
                     periods_held=2, total_trades=1, restart_count=0,
                     ts_ms=1_000),
        WorkerStatus(symbol="ETHUSDT", state=5, heartbeat=time.time(),
                     periods_held=0, total_trades=0, restart_count=0,
                     ts_ms=1_000),
    ]
    collector.record_worker_states(statuses)

    assert _get_gauge(m.worker_state, "BYBIT", "BTCUSDT") == 3.0  # HOLDING
    assert _get_gauge(m.worker_state, "BYBIT", "ETHUSDT") == 5.0  # STOPPED
    assert _get_gauge(m.active_workers, "BYBIT") == 1.0           # only BTCUSDT is alive


def test_record_hedge_result_increments_counter():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])

    before_success = m.hedge_success_total.labels("BYBIT", "SOLUSDT")._value.get()
    collector.record_hedge_result("SOLUSDT", success=True, latency_ms=42.5)
    after_success = m.hedge_success_total.labels("BYBIT", "SOLUSDT")._value.get()

    assert after_success == before_success + 1


def test_record_hedge_failure_increments_counter():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])

    before = m.hedge_failure_total.labels("BYBIT", "XRPUSDT")._value.get()
    collector.record_hedge_result("XRPUSDT", success=False, latency_ms=99.0)
    after = m.hedge_failure_total.labels("BYBIT", "XRPUSDT")._value.get()

    assert after == before + 1


def test_set_ws_connected():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])

    collector.set_ws_connected(True)
    assert _get_gauge(m.ws_connected, "BYBIT") == 1.0

    collector.set_ws_connected(False)
    assert _get_gauge(m.ws_connected, "BYBIT") == 0.0


def test_record_ws_reconnect_increments_counter():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])

    before = m.ws_reconnects_total.labels("BYBIT")._value.get()
    collector.record_ws_reconnect()
    after = m.ws_reconnects_total.labels("BYBIT")._value.get()

    assert after == before + 1


def test_set_equity():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])
    collector.set_equity(102_000.0)
    assert _get_gauge(m.equity_usd, "BYBIT") == pytest.approx(102_000.0)


def test_set_balance():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", [])
    collector.set_balance("USDT", 95_000.0)
    assert _get_gauge(m.balance_available, "BYBIT", "USDT") == pytest.approx(95_000.0)


# ── Collector lifecycle ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_collector_start_creates_tasks_per_symbol():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT", "ETHUSDT"])
    collector.start()
    await asyncio.sleep(0)

    # 2 tasks per symbol (basis, funding) + 2 portfolio tasks = 6
    assert len(collector._tasks) == 6
    collector.stop()


@pytest.mark.asyncio
async def test_collector_stop_clears_tasks():
    bus = MarketDataBus()
    collector = MetricsCollector(bus, "BYBIT", ["BTCUSDT"])
    collector.start()
    await asyncio.sleep(0)
    collector.stop()
    assert collector._tasks == []
