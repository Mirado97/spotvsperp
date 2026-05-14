from __future__ import annotations

from collections import deque

import numpy as np

# Bybit typical funding rate per 8h interval
TYPICAL_RATE: float = 0.0001       # 0.01%
EXTREME_THRESHOLD: float = 0.0003  # 3× typical
ACCEL_THRESHOLD: float = 0.00005   # half of typical per period


class FundingHistory:
    """
    Rolling window of funding rate observations with statistical analysis.

    Window defaults to 168 periods = 56 days at 8h intervals.
    EWMA span of 8 periods gives ~64h half-weight window for regime detection.
    """

    def __init__(self, window: int = 168, ewma_span: int = 8) -> None:
        self._rates: deque[float] = deque(maxlen=window)
        self._ts: deque[int] = deque(maxlen=window)
        self._ewma_span = ewma_span
        self._extreme_streak: int = 0

    # ── Ingestion ──────────────────────────────────────────────────────────────

    def push(self, rate: float, ts_ms: int) -> None:
        self._rates.append(rate)
        self._ts.append(ts_ms)
        if abs(rate) >= EXTREME_THRESHOLD:
            self._extreme_streak += 1
        else:
            self._extreme_streak = 0

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._rates)

    @property
    def is_ready(self) -> bool:
        return len(self._rates) >= 3

    @property
    def extreme_streak(self) -> int:
        return self._extreme_streak

    # ── Point statistics ──────────────────────────────────────────────────────

    @property
    def mean(self) -> float:
        if not self._rates:
            return 0.0
        return float(np.mean(self._rates))

    @property
    def std(self) -> float:
        if len(self._rates) < 2:
            return 0.0
        return float(np.std(self._rates, ddof=1))

    @property
    def ewma(self) -> float:
        """Exponentially weighted moving average (more weight on recent rates)."""
        if not self._rates:
            return 0.0
        alpha = 2.0 / (self._ewma_span + 1)
        result = self._rates[0]
        for v in list(self._rates)[1:]:
            result = alpha * v + (1 - alpha) * result
        return result

    @property
    def acceleration(self) -> float:
        """Instantaneous rate of change: last - previous."""
        if len(self._rates) < 2:
            return 0.0
        rates = list(self._rates)
        return rates[-1] - rates[-2]

    @property
    def acceleration_direction(self) -> str:
        a = self.acceleration
        if a > ACCEL_THRESHOLD:
            return "rising"
        if a < -ACCEL_THRESHOLD:
            return "falling"
        return "stable"

    @property
    def is_accelerating(self) -> bool:
        return abs(self.acceleration) > ACCEL_THRESHOLD

    # ── Regime ────────────────────────────────────────────────────────────────

    @property
    def regime(self) -> str:
        """Classify funding regime based on EWMA to smooth out noise."""
        e = self.ewma
        if e > EXTREME_THRESHOLD:
            return "strongly_bullish"
        if e > TYPICAL_RATE:
            return "mildly_bullish"
        if e < -EXTREME_THRESHOLD:
            return "strongly_bearish"
        if e < -TYPICAL_RATE:
            return "mildly_bearish"
        return "neutral"

    # ── Distribution ──────────────────────────────────────────────────────────

    def z_score(self, rate: float) -> float:
        std = self.std
        if std == 0.0:
            return 0.0
        return (rate - self.mean) / std

    def percentile_of(self, rate: float) -> float:
        if not self._rates:
            return 0.5
        return float(np.mean(np.array(self._rates) <= rate))

    def confidence_interval(self, level: float = 0.95) -> tuple[float, float]:
        """95% CI. Uses empirical percentiles when enough data, else ±1.96σ."""
        if len(self._rates) < 10:
            z = 1.96
            m, s = self.mean, self.std
            return m - z * s, m + z * s
        alpha = (1 - level) / 2
        arr = np.array(self._rates)
        return (
            float(np.percentile(arr, alpha * 100)),
            float(np.percentile(arr, (1 - alpha) * 100)),
        )

    # ── Prediction ────────────────────────────────────────────────────────────

    def predicted_next(self, exchange_prediction: float) -> float:
        """
        Blended prediction:
          50% exchange-provided prediction (based on current premium index)
          30% EWMA (trend-adjusted mean)
          20% EWMA + momentum (extrapolation)
        """
        if not self.is_ready:
            return exchange_prediction
        ewma = self.ewma
        extrapolated = ewma + self.acceleration
        return 0.5 * exchange_prediction + 0.3 * ewma + 0.2 * extrapolated

    # ── Carry metrics ─────────────────────────────────────────────────────────

    def annualized_carry(self) -> float:
        return self.mean * (365 * 24 / 8)

    def daily_carry(self) -> float:
        return self.mean * (24 / 8)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def snapshot(self) -> dict[str, float]:
        ci_lo, ci_hi = self.confidence_interval()
        return {
            "count": float(self.count),
            "mean": self.mean,
            "std": self.std,
            "ewma": self.ewma,
            "acceleration": self.acceleration,
            "extreme_streak": float(self.extreme_streak),
            "annualized_carry": self.annualized_carry(),
            "ci_lower": ci_lo,
            "ci_upper": ci_hi,
        }
