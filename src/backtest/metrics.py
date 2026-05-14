from __future__ import annotations

import numpy as np

from src.backtest.models import BacktestMetrics, TradeRecord


def compute_metrics(trades: list[TradeRecord], initial_equity: float) -> BacktestMetrics:
    """Compute aggregate performance statistics from a list of closed trades."""
    closed = [t for t in trades if not t.is_open and t.exit_ts_ms is not None]

    if not closed:
        return BacktestMetrics(
            total_trades=0, win_rate=0.0, gross_pnl=0.0, total_fees=0.0,
            total_net_pnl=0.0, avg_net_pnl=0.0, avg_holding_periods=0.0,
            max_drawdown=0.0, sharpe_ratio=0.0, calmar_ratio=0.0, return_pct=0.0,
        )

    net_pnls = np.array([t.net_pnl for t in closed])
    wins = int((net_pnls > 0).sum())
    total_net = float(net_pnls.sum())
    total_fees = float(sum(t.fees for t in closed))
    gross_pnl = float(sum(t.gross_pnl for t in closed))

    # Equity curve → max drawdown
    equity = initial_equity + np.cumsum(net_pnls)
    peak = np.maximum.accumulate(equity)
    drawdown = (peak - equity) / peak
    max_dd = float(drawdown.max())

    # Annualised Sharpe (1095 eight-hour periods per year)
    _PERIODS_PER_YEAR = 1095.0
    std = float(net_pnls.std())
    sharpe = float(net_pnls.mean() / std * (_PERIODS_PER_YEAR ** 0.5)) if std > 0 else 0.0

    return_pct = total_net / initial_equity
    calmar = return_pct / max_dd if max_dd > 0 else 0.0

    return BacktestMetrics(
        total_trades=len(closed),
        win_rate=wins / len(closed),
        gross_pnl=gross_pnl,
        total_fees=total_fees,
        total_net_pnl=total_net,
        avg_net_pnl=total_net / len(closed),
        avg_holding_periods=float(sum(t.periods_held for t in closed) / len(closed)),
        max_drawdown=max_dd,
        sharpe_ratio=sharpe,
        calmar_ratio=calmar,
        return_pct=return_pct,
    )
