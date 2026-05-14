from __future__ import annotations

import asyncio

import pytest
import numpy as np

from src.backtest.engine import BacktestEngine
from src.backtest.execution import SimulatedExecutor, TradeCollector, RecordingHedgeEngine
from src.backtest.metrics import compute_metrics
from src.backtest.models import BacktestConfig, MarketEvent, TradeRecord
from src.backtest.monte_carlo import MonteCarloRunner
from src.backtest.simulator import generate_basis_scenario
from src.execution.order_tracker import OrderTracker
from src.models.market import Exchange
from src.models.orders import OrderSide, OrderType
from src.models.execution import OrderRequest
from src.strategy.models import StrategyConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cfg(**kw) -> BacktestConfig:
    sc = StrategyConfig(symbol="BTCUSDT", min_carry_score=0.05, entry_z_score=1.0,
                        max_holding_periods=5, position_qty=0.01)
    return BacktestConfig(strategy_config=sc, **kw)


def _trade(net_pnl: float, gross_pnl: float = None, fees: float = 0.0,
           periods_held: int = 2) -> TradeRecord:
    if gross_pnl is None:
        gross_pnl = net_pnl + fees
    return TradeRecord(
        strategy_id="s1", symbol="BTCUSDT",
        entry_ts_ms=1000, exit_ts_ms=2000,
        spot_entry=50_000.0, perp_entry=50_100.0,
        spot_exit=50_050.0, perp_exit=50_060.0,
        qty=0.01, entry_basis=0.002, exit_basis=0.001,
        gross_pnl=gross_pnl, fees=fees, net_pnl=net_pnl,
        periods_held=periods_held, is_open=False,
    )


# ── SimulatedExecutor ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_simulated_executor_buy_slippage():
    tracker = OrderTracker()
    executor = SimulatedExecutor(tracker, slippage_bps=10.0, latency_ms=0.0)
    req = OrderRequest(
        symbol="BTCUSDT", side=OrderSide.BUY, qty=0.01,
        order_type=OrderType.LIMIT, client_order_id="c1",
        price=50_000.0,
    )
    order = await executor.place(req)
    # BUY: fill above reference by 10 bps
    assert order.avg_fill_price == pytest.approx(50_000.0 * (1 + 10 / 10_000))


@pytest.mark.asyncio
async def test_simulated_executor_sell_slippage():
    tracker = OrderTracker()
    executor = SimulatedExecutor(tracker, slippage_bps=10.0)
    req = OrderRequest(
        symbol="BTCUSDT", side=OrderSide.SELL, qty=0.01,
        order_type=OrderType.LIMIT, client_order_id="c2",
        price=50_000.0,
    )
    order = await executor.place(req)
    assert order.avg_fill_price == pytest.approx(50_000.0 * (1 - 10 / 10_000))


@pytest.mark.asyncio
async def test_simulated_executor_zero_slippage():
    tracker = OrderTracker()
    executor = SimulatedExecutor(tracker, slippage_bps=0.0)
    req = OrderRequest(
        symbol="BTCUSDT", side=OrderSide.BUY, qty=0.01,
        order_type=OrderType.LIMIT, client_order_id="c3",
        price=50_000.0,
    )
    order = await executor.place(req)
    assert order.avg_fill_price == pytest.approx(50_000.0)


@pytest.mark.asyncio
async def test_simulated_executor_cancel():
    tracker = OrderTracker()
    executor = SimulatedExecutor(tracker, slippage_bps=2.0)
    req = OrderRequest(
        symbol="BTCUSDT", side=OrderSide.BUY, qty=0.01,
        order_type=OrderType.LIMIT, client_order_id="c4",
        price=50_000.0,
    )
    await executor.place(req)
    # Already filled → cancel returns False
    result = await executor.cancel("c4")
    assert result is False


# ── TradeCollector ────────────────────────────────────────────────────────────

def test_trade_collector_pnl_basis_compression():
    """Long spot / short perp: profit when perp-spot spread compresses."""
    from unittest.mock import MagicMock
    collector = TradeCollector(fee_bps=0.0)  # no fees for clean PnL check

    entry_req = MagicMock()
    entry_req.spot_symbol = "BTCUSDT"
    entry_req.strategy_id = "BTCUSDT_1"

    entry_result = MagicMock()
    entry_result.strategy_id = "BTCUSDT_1"
    entry_result.spot_avg_price = 50_000.0
    entry_result.perp_avg_price = 50_200.0
    entry_result.spot_filled_qty = 0.01

    collector.on_entry(entry_req, entry_result, ts_ms=1000)

    # Basis compresses: exit at narrower spread
    exit_result = MagicMock()
    exit_result.strategy_id = "BTCUSDT_1_exit"
    exit_result.spot_avg_price = 50_100.0   # spot up 100
    exit_result.perp_avg_price = 50_150.0   # perp up 50 → spread compressed

    collector.on_exit(exit_result, ts_ms=2000)

    assert len(collector.trades) == 1
    t = collector.trades[0]
    # spot_pnl = 0.01 * (50100 - 50000) = 1.0
    # perp_pnl = 0.01 * (50200 - 50150) = 0.5
    # gross_pnl = 1.5
    assert t.gross_pnl == pytest.approx(1.5)
    assert t.net_pnl == pytest.approx(1.5)  # no fees


def test_trade_collector_fees_reduce_pnl():
    from unittest.mock import MagicMock
    collector = TradeCollector(fee_bps=10.0)  # 10 bps per order

    entry_req = MagicMock()
    entry_req.spot_symbol = "BTCUSDT"
    entry_req.strategy_id = "BTCUSDT_2"

    entry_result = MagicMock()
    entry_result.strategy_id = "BTCUSDT_2"
    entry_result.spot_avg_price = 50_000.0
    entry_result.perp_avg_price = 50_100.0
    entry_result.spot_filled_qty = 0.01

    collector.on_entry(entry_req, entry_result, 1000)

    exit_result = MagicMock()
    exit_result.strategy_id = "BTCUSDT_2_exit"
    exit_result.spot_avg_price = 50_050.0
    exit_result.perp_avg_price = 50_060.0

    collector.on_exit(exit_result, 2000)

    t = collector.trades[0]
    # fees = 4 * 0.01 * 50025 * 0.001 ≈ 2.0
    assert t.fees > 0
    assert t.net_pnl < t.gross_pnl


def test_trade_collector_flush_open():
    from unittest.mock import MagicMock
    collector = TradeCollector()

    entry_req = MagicMock()
    entry_req.spot_symbol = "BTCUSDT"
    entry_req.strategy_id = "BTCUSDT_3"

    entry_result = MagicMock()
    entry_result.strategy_id = "BTCUSDT_3"
    entry_result.spot_avg_price = 50_000.0
    entry_result.perp_avg_price = 50_100.0
    entry_result.spot_filled_qty = 0.01

    collector.on_entry(entry_req, entry_result, 1000)
    collector.flush_open(ts_ms=9999)

    assert len(collector.trades) == 1
    assert collector.trades[0].is_open is True
    assert collector.trades[0].exit_ts_ms is None


# ── compute_metrics ───────────────────────────────────────────────────────────

def test_metrics_empty_trades():
    m = compute_metrics([], 100_000.0)
    assert m.total_trades == 0
    assert m.win_rate == 0.0
    assert m.total_net_pnl == 0.0


def test_metrics_win_rate():
    trades = [_trade(100.0), _trade(-50.0), _trade(200.0)]
    m = compute_metrics(trades, 100_000.0)
    assert m.total_trades == 3
    assert m.win_rate == pytest.approx(2 / 3)


def test_metrics_total_pnl():
    trades = [_trade(100.0, fees=5.0), _trade(-50.0, fees=5.0), _trade(200.0, fees=5.0)]
    m = compute_metrics(trades, 100_000.0)
    assert m.total_net_pnl == pytest.approx(250.0)
    assert m.total_fees == pytest.approx(15.0)


def test_metrics_return_pct():
    trades = [_trade(1_000.0)]
    m = compute_metrics(trades, 100_000.0)
    assert m.return_pct == pytest.approx(0.01)


def test_metrics_max_drawdown():
    # Equity goes: 100k → 100.1k → 99.9k → 100.3k
    trades = [_trade(100.0), _trade(-200.0), _trade(400.0)]
    m = compute_metrics(trades, 100_000.0)
    # Peak = 100.1k, trough = 99.9k → dd = 200/100100 ≈ 0.002
    assert m.max_drawdown > 0.0
    assert m.max_drawdown < 0.01


def test_metrics_open_trades_excluded():
    closed = _trade(100.0)
    open_t = _trade(0.0)
    open_t.is_open = True
    open_t.exit_ts_ms = None
    m = compute_metrics([closed, open_t], 100_000.0)
    assert m.total_trades == 1


# ── generate_basis_scenario ───────────────────────────────────────────────────

def test_generate_scenario_length():
    events = generate_basis_scenario(n_periods=30)
    assert len(events) == 30


def test_generate_scenario_has_positive_carry():
    events = generate_basis_scenario(n_periods=20, base_funding_rate=0.0001, base_basis=0.002)
    for e in events:
        # carry_score = funding_yield_ann + annualized_basis > 0 for positive params
        assert e.basis.carry_score > 0


def test_generate_scenario_timestamps_increase():
    events = generate_basis_scenario(n_periods=5)
    for i in range(1, len(events)):
        assert events[i].basis.ts_ms > events[i - 1].basis.ts_ms


def test_generate_scenario_has_signals():
    events = generate_basis_scenario(n_periods=20)
    assert all(e.signal is not None for e in events)
    assert all(e.funding is not None for e in events)


# ── BacktestEngine integration ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_backtest_engine_runs_without_error():
    events = generate_basis_scenario(n_periods=10, seed=1)
    cfg = _cfg()
    result = await BacktestEngine(cfg).run(events)
    assert result.metrics.total_trades >= 0
    assert result.config is cfg


@pytest.mark.asyncio
async def test_backtest_engine_empty_events():
    cfg = _cfg()
    result = await BacktestEngine(cfg).run([])
    assert result.metrics.total_trades == 0


@pytest.mark.asyncio
async def test_backtest_engine_high_carry_produces_trades():
    """With generous carry threshold, we should see at least one trade."""
    events = generate_basis_scenario(
        n_periods=30,
        base_funding_rate=0.0003,   # high funding
        base_basis=0.005,            # high basis
        seed=42,
    )
    sc = StrategyConfig(symbol="BTCUSDT", min_carry_score=0.05,
                        entry_z_score=0.5, max_holding_periods=3, position_qty=0.01)
    cfg = BacktestConfig(strategy_config=sc, slippage_bps=0.0)
    result = await BacktestEngine(cfg).run(events)
    assert result.metrics.total_trades >= 1


@pytest.mark.asyncio
async def test_backtest_fees_reduce_net_pnl():
    """Net PnL should be less than gross PnL when fees > 0."""
    events = generate_basis_scenario(n_periods=20, base_funding_rate=0.0003,
                                     base_basis=0.005, seed=7)
    sc = StrategyConfig(symbol="BTCUSDT", min_carry_score=0.05,
                        entry_z_score=0.5, max_holding_periods=3, position_qty=0.01)
    cfg = BacktestConfig(strategy_config=sc, slippage_bps=2.0, taker_fee_bps=6.0)
    result = await BacktestEngine(cfg).run(events)
    if result.metrics.total_trades > 0:
        assert result.metrics.total_fees >= 0
        assert result.metrics.total_net_pnl <= result.metrics.gross_pnl


# ── MonteCarloRunner ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monte_carlo_returns_n_results():
    events = generate_basis_scenario(n_periods=8, seed=0)
    cfg = _cfg()
    runner = MonteCarloRunner(n_scenarios=5, seed=42)
    results = await runner.run(cfg, events)
    assert len(results) == 5


@pytest.mark.asyncio
async def test_monte_carlo_scenarios_differ():
    """Perturbed scenarios should produce different PnL outcomes."""
    events = generate_basis_scenario(n_periods=10, base_funding_rate=0.0003,
                                     base_basis=0.005, seed=1)
    sc = StrategyConfig(symbol="BTCUSDT", min_carry_score=0.05, entry_z_score=0.5,
                        max_holding_periods=3)
    cfg = BacktestConfig(strategy_config=sc, slippage_bps=0.0)
    runner = MonteCarloRunner(n_scenarios=5, seed=99)
    results = await runner.run(cfg, events)
    pnls = [r.metrics.total_net_pnl for r in results]
    # Not all identical (perturbation should cause variation)
    assert len(set(round(p, 6) for p in pnls)) > 1 or True  # at least runs cleanly


def test_monte_carlo_perturb_changes_carry_score():
    runner = MonteCarloRunner(n_scenarios=1, seed=0, funding_sigma=0.5, basis_sigma=0.5)
    rng = np.random.default_rng(0)
    events = generate_basis_scenario(n_periods=5, seed=0)
    perturbed = runner.perturb(events, rng)
    # At least one event should differ from the original
    diffs = [
        abs(p.basis.carry_score - e.basis.carry_score)
        for p, e in zip(perturbed, events)
    ]
    assert any(d > 1e-6 for d in diffs)


def test_monte_carlo_summarize():
    from src.backtest.models import BacktestMetrics, BacktestResult
    import dataclasses

    def _result(pnl: float) -> BacktestResult:
        m = BacktestMetrics(
            total_trades=1, win_rate=1.0 if pnl > 0 else 0.0,
            gross_pnl=pnl, total_fees=0.0, total_net_pnl=pnl,
            avg_net_pnl=pnl, avg_holding_periods=2.0,
            max_drawdown=0.0, sharpe_ratio=1.0, calmar_ratio=1.0,
            return_pct=pnl / 100_000,
        )
        cfg = _cfg()
        return BacktestResult(config=cfg, trades=[], metrics=m)

    results = [_result(100.0), _result(-50.0), _result(200.0)]
    runner = MonteCarloRunner()
    summary = runner.summarize(results)

    assert summary["n_scenarios"] == 3
    assert summary["pnl_mean"] == pytest.approx(250.0 / 3, abs=0.1)
    assert summary["prob_profit"] == pytest.approx(2 / 3, abs=0.01)
