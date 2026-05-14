from __future__ import annotations

import dataclasses

from src.basis.models import BasisSnapshot, MeanReversionSignal
from src.funding.models import FundingAnalysis
from src.strategy.models import StrategyConfig


@dataclasses.dataclass
class MarketEvent:
    """One time-step of market data fed to the backtester."""
    basis: BasisSnapshot
    funding: FundingAnalysis | None = None
    signal: MeanReversionSignal | None = None


@dataclasses.dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""
    strategy_config: StrategyConfig
    slippage_bps: float = 2.0          # bps per side (both legs)
    taker_fee_bps: float = 6.0         # taker fee bps per order
    latency_ms: float = 0.0            # simulated order latency (0 = instant)
    initial_equity: float = 100_000.0


@dataclasses.dataclass
class TradeRecord:
    """Closed (or still-open) carry trade."""
    strategy_id: str
    symbol: str
    entry_ts_ms: int
    exit_ts_ms: int | None
    spot_entry: float
    perp_entry: float
    spot_exit: float | None
    perp_exit: float | None
    qty: float
    entry_basis: float          # (perp_entry - spot_entry) / spot_entry
    exit_basis: float | None    # (perp_exit  - spot_exit ) / spot_exit
    gross_pnl: float
    fees: float
    net_pnl: float
    periods_held: int
    is_open: bool = False       # True if position still open at end of backtest


@dataclasses.dataclass
class BacktestMetrics:
    """Aggregate performance statistics for a completed backtest."""
    total_trades: int
    win_rate: float
    gross_pnl: float
    total_fees: float
    total_net_pnl: float
    avg_net_pnl: float
    avg_holding_periods: float
    max_drawdown: float
    sharpe_ratio: float
    calmar_ratio: float
    return_pct: float


@dataclasses.dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[TradeRecord]
    metrics: BacktestMetrics
