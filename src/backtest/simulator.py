from __future__ import annotations

import numpy as np

from src.basis.models import BasisSnapshot, MeanReversionSignal
from src.funding.models import FundingAnalysis
from src.models.market import Exchange
from src.backtest.models import MarketEvent

_PERIODS_PER_YEAR = 1095.0   # 8-hour funding periods


def generate_basis_scenario(
    symbol: str = "BTCUSDT",
    exchange: str = "BYBIT",
    n_periods: int = 50,
    base_spot: float = 50_000.0,
    base_funding_rate: float = 0.0001,   # 0.01% per 8h
    base_basis: float = 0.002,           # 0.2% perp premium
    spot_vol: float = 0.002,             # per-period spot return vol
    basis_mean_reversion: float = 0.85,  # AR(1) coefficient for basis
    basis_noise: float = 0.0005,         # per-period basis noise
    funding_mean_reversion: float = 0.90,
    funding_noise: float = 0.00002,
    seed: int = 0,
) -> list[MarketEvent]:
    """
    Synthetic carry scenario: mean-reverting basis + random-walk spot.

    Each event represents one 8-hour funding period.
    """
    rng = np.random.default_rng(seed)
    exch = Exchange[exchange]

    events: list[MarketEvent] = []
    spot = base_spot
    basis = base_basis
    funding_rate = base_funding_rate
    ts = 1_700_000_000_000  # epoch ms

    for _ in range(n_periods):
        # Spot random walk
        spot *= 1.0 + rng.normal(0.0, spot_vol)
        # Mean-reverting basis
        basis = basis_mean_reversion * basis + (1.0 - basis_mean_reversion) * base_basis \
                + rng.normal(0.0, basis_noise)
        basis = max(0.0, basis)
        perp = spot * (1.0 + basis)
        # Mean-reverting funding
        funding_rate = funding_mean_reversion * funding_rate \
                       + (1.0 - funding_mean_reversion) * base_funding_rate \
                       + rng.normal(0.0, funding_noise)
        funding_rate = max(0.0, funding_rate)

        snap = BasisSnapshot(
            exchange=exch, symbol=symbol,
            spot_mid=float(spot), perp_mid=float(perp),
            basis=float(basis), basis_bps=float(basis * 10_000),
            annualized_basis=float(basis * _PERIODS_PER_YEAR),
            perp_premium=float(perp - spot),
            funding_rate=float(funding_rate),
            predicted_funding=float(funding_rate),
            funding_yield_ann=float(funding_rate * _PERIODS_PER_YEAR),
            ts_ms=ts,
        )

        # Simple z-score signal from basis deviation
        z = (basis - base_basis) / (basis_noise + 1e-9)
        signal = MeanReversionSignal(
            exchange=exch, symbol=symbol,
            basis_current=float(basis), basis_mean=base_basis,
            basis_std=float(basis_noise),
            z_score=float(z), half_life_h=24.0,
            is_signal=abs(z) >= 1.0,
            direction="long_carry" if z >= 0 else "short_carry",
            signal_strength=float(abs(z)),
            ts_ms=ts,
        )

        analysis = _make_funding_analysis(exch, symbol, float(funding_rate), ts)
        events.append(MarketEvent(basis=snap, funding=analysis, signal=signal))
        ts += 8 * 3_600_000

    return events


def _make_funding_analysis(
    exchange: Exchange,
    symbol: str,
    rate: float,
    ts_ms: int,
) -> FundingAnalysis:
    return FundingAnalysis(
        exchange=exchange, symbol=symbol,
        current_rate=rate, predicted_rate=rate, ewma_rate=rate,
        mean_rate=rate, std_rate=rate * 0.5,
        z_score=0.0, percentile=0.5,
        predicted_next=rate, ci_lower=rate * 0.5, ci_upper=rate * 1.5,
        regime="mildly_bullish" if rate >= 0 else "mildly_bearish",
        acceleration=0.0, is_accelerating=False, acceleration_direction="stable",
        is_extreme=abs(rate) > 0.003,
        rate_direction="longs_paying" if rate >= 0 else "shorts_paying",
        extreme_streak=0,
        annualized_carry=rate * _PERIODS_PER_YEAR,
        daily_carry=rate * 3,
        ts_ms=ts_ms,
    )
