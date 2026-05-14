from __future__ import annotations

import msgspec

from src.models.market import Exchange


class FundingAnalysis(msgspec.Struct, frozen=True, gc=False):
    """
    Full funding analysis snapshot for one symbol.
    Published to bus at: "funding_analysis.{exchange}.{symbol}"
    """
    exchange: Exchange
    symbol: str

    # ── Current state ────────────────────────────────────────────────────────
    current_rate: float         # latest 8h funding rate
    predicted_rate: float       # exchange-provided prediction for next period
    ewma_rate: float            # our EWMA estimate (span=8 periods = 64h)

    # ── Rolling statistics ───────────────────────────────────────────────────
    mean_rate: float
    std_rate: float
    z_score: float              # (current - mean) / std
    percentile: float           # empirical percentile in [0, 1]

    # ── Prediction ───────────────────────────────────────────────────────────
    predicted_next: float       # blended prediction (exchange + EWMA + momentum)
    ci_lower: float             # 95% confidence interval lower bound
    ci_upper: float

    # ── Regime ───────────────────────────────────────────────────────────────
    regime: str                 # "strongly_bullish" | "mildly_bullish" | "neutral"
                                # | "mildly_bearish" | "strongly_bearish"

    # ── Acceleration ─────────────────────────────────────────────────────────
    acceleration: float         # rate[-1] - rate[-2] (velocity of funding change)
    is_accelerating: bool       # |acceleration| > threshold
    acceleration_direction: str # "rising" | "falling" | "stable"

    # ── Extreme conditions ────────────────────────────────────────────────────
    is_extreme: bool            # |current_rate| > EXTREME_THRESHOLD
    rate_direction: str         # "longs_paying" | "shorts_paying" | "neutral"
    extreme_streak: int         # consecutive 8h periods at extreme level

    # ── Carry metrics ─────────────────────────────────────────────────────────
    annualized_carry: float     # mean_rate * 1095
    daily_carry: float          # mean_rate * 3

    ts_ms: int

    @property
    def is_positive_carry(self) -> bool:
        return self.current_rate > 0

    @property
    def is_squeeze_risk(self) -> bool:
        """Elevated risk of a squeeze: extreme + accelerating for 2+ periods."""
        return self.is_extreme and self.is_accelerating and self.extreme_streak >= 2
