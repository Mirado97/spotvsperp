from __future__ import annotations

import numpy as np

from src.basis.models import BasisSnapshot
from src.backtest.engine import BacktestEngine
from src.backtest.models import BacktestConfig, BacktestResult, MarketEvent
from src.core.logging_setup import get_logger

logger = get_logger(__name__)


class MonteCarloRunner:
    """
    Runs N independent backtest scenarios by perturbing the base market data.

    Perturbation model:
      - Funding rate multiplied by log-normal factor (sigma=funding_sigma)
      - Basis multiplied by log-normal factor     (sigma=basis_sigma)
      - FundingAnalysis and signals carried through unchanged (conservative)

    Usage:
        runner = MonteCarloRunner(n_scenarios=200)
        results = await runner.run(config, base_events)
        pnls = [r.metrics.total_net_pnl for r in results]
    """

    def __init__(
        self,
        n_scenarios: int = 100,
        seed: int = 42,
        funding_sigma: float = 0.20,   # log-normal std for funding multiplier
        basis_sigma: float = 0.15,     # log-normal std for basis multiplier
    ) -> None:
        self._n = n_scenarios
        self._seed = seed
        self._f_sigma = funding_sigma
        self._b_sigma = basis_sigma

    def perturb(
        self,
        events: list[MarketEvent],
        rng: np.random.Generator,
    ) -> list[MarketEvent]:
        """Apply one random perturbation to a scenario."""
        # One multiplier per series (correlated across time-steps in one scenario)
        f_mult = float(np.exp(rng.normal(0, self._f_sigma)))
        b_mult = float(np.exp(rng.normal(0, self._b_sigma)))

        perturbed: list[MarketEvent] = []
        for e in events:
            new_funding = max(0.0, e.basis.funding_rate * f_mult)
            new_basis = max(0.0, e.basis.basis * b_mult)
            new_perp = e.basis.spot_mid * (1.0 + new_basis)

            new_snap = BasisSnapshot(
                exchange=e.basis.exchange,
                symbol=e.basis.symbol,
                spot_mid=e.basis.spot_mid,
                perp_mid=new_perp,
                basis=new_basis,
                basis_bps=new_basis * 10_000,
                annualized_basis=new_basis * 1095,
                perp_premium=new_perp - e.basis.spot_mid,
                funding_rate=new_funding,
                predicted_funding=new_funding,
                funding_yield_ann=new_funding * 1095,
                ts_ms=e.basis.ts_ms,
            )
            perturbed.append(MarketEvent(
                basis=new_snap,
                funding=e.funding,    # kept from base scenario
                signal=e.signal,      # kept from base scenario
            ))
        return perturbed

    async def run(
        self,
        config: BacktestConfig,
        base_events: list[MarketEvent],
    ) -> list[BacktestResult]:
        """Run N perturbed backtests and return all results."""
        rng = np.random.default_rng(self._seed)
        results: list[BacktestResult] = []

        for i in range(self._n):
            scenario = self.perturb(base_events, rng)
            engine = BacktestEngine(config)
            result = await engine.run(scenario)
            results.append(result)

        net_pnls = [r.metrics.total_net_pnl for r in results]
        logger.info(
            "monte_carlo.complete",
            n=self._n,
            mean_pnl=round(float(np.mean(net_pnls)), 2),
            p5_pnl=round(float(np.percentile(net_pnls, 5)), 2),
            p95_pnl=round(float(np.percentile(net_pnls, 95)), 2),
        )
        return results

    def summarize(self, results: list[BacktestResult]) -> dict:
        """Return aggregate statistics across all Monte Carlo runs."""
        pnls = np.array([r.metrics.total_net_pnl for r in results])
        win_rates = np.array([r.metrics.win_rate for r in results])
        sharpes = np.array([r.metrics.sharpe_ratio for r in results])
        drawdowns = np.array([r.metrics.max_drawdown for r in results])
        return {
            "n_scenarios": len(results),
            "pnl_mean":    round(float(pnls.mean()), 2),
            "pnl_std":     round(float(pnls.std()), 2),
            "pnl_p5":      round(float(np.percentile(pnls, 5)), 2),
            "pnl_p25":     round(float(np.percentile(pnls, 25)), 2),
            "pnl_p50":     round(float(np.percentile(pnls, 50)), 2),
            "pnl_p75":     round(float(np.percentile(pnls, 75)), 2),
            "pnl_p95":     round(float(np.percentile(pnls, 95)), 2),
            "prob_profit":  round(float((pnls > 0).mean()), 3),
            "win_rate_mean": round(float(win_rates.mean()), 3),
            "sharpe_mean":  round(float(sharpes.mean()), 3),
            "max_dd_mean":  round(float(drawdowns.mean()), 4),
            "max_dd_p95":   round(float(np.percentile(drawdowns, 95)), 4),
        }
