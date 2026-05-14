from __future__ import annotations

from collections import deque

import numpy as np


class BasisHistory:
    """
    Rolling window of basis values with on-demand statistical analysis.

    Uses a fixed-size deque; oldest values are evicted automatically.
    All statistical methods require at least `min_samples` values.

    Half-life estimation uses OLS on the AR(1) process:
        Δbasis_t = α + β * basis_{t-1} + ε
        half_life = -ln(2) / β   (valid when β < 0)

    Each observation is assumed to be one 8-hour funding period apart,
    so half-life is returned in hours (periods * 8).
    """

    MIN_SAMPLES = 20
    MIN_HALF_LIFE_SAMPLES = 30

    def __init__(self, window: int = 200) -> None:
        self._data: deque[float] = deque(maxlen=window)

    def push(self, value: float) -> None:
        self._data.append(value)

    @property
    def count(self) -> int:
        return len(self._data)

    @property
    def is_ready(self) -> bool:
        return len(self._data) >= self.MIN_SAMPLES

    # ── Point statistics ──────────────────────────────────────────────────────

    @property
    def mean(self) -> float:
        if not self._data:
            return 0.0
        return float(np.mean(self._data))

    @property
    def std(self) -> float:
        if len(self._data) < 2:
            return 0.0
        return float(np.std(self._data, ddof=1))

    @property
    def min(self) -> float:
        return float(min(self._data)) if self._data else 0.0

    @property
    def max(self) -> float:
        return float(max(self._data)) if self._data else 0.0

    # ── Derived statistics ────────────────────────────────────────────────────

    def z_score(self, current: float) -> float:
        """Z-score of current value relative to rolling mean/std."""
        std = self.std
        if std == 0.0:
            return 0.0
        return (current - self.mean) / std

    def percentile(self, current: float) -> float:
        """Empirical percentile of current value in [0, 1]."""
        if not self._data:
            return 0.5
        arr = np.array(self._data)
        return float(np.mean(arr <= current))

    def bollinger_bands(self, n_std: float = 2.0) -> tuple[float, float, float]:
        """Returns (lower_band, mean, upper_band)."""
        m, s = self.mean, self.std
        return m - n_std * s, m, m + n_std * s

    def half_life_h(self) -> float:
        """
        Estimate mean-reversion half-life in hours.
        Returns float('inf') if series is not mean-reverting (β ≥ 0)
        or if there's insufficient data.
        """
        if len(self._data) < self.MIN_HALF_LIFE_SAMPLES:
            return float("inf")

        y = np.array(self._data)
        y_lag = y[:-1]
        y_diff = np.diff(y)

        X = np.column_stack([np.ones_like(y_lag), y_lag])
        try:
            beta = np.linalg.lstsq(X, y_diff, rcond=None)[0][1]
        except np.linalg.LinAlgError:
            return float("inf")

        if beta >= 0.0:
            return float("inf")

        # Each period = 8h funding interval
        return float(-np.log(2) / beta * 8.0)

    def autocorrelation(self, lag: int = 1) -> float:
        """Lag-N autocorrelation. Useful for confirming mean reversion (negative AC at lag 1)."""
        if len(self._data) < lag + 2:
            return 0.0
        arr = np.array(self._data)
        return float(np.corrcoef(arr[:-lag], arr[lag:])[0, 1])

    def snapshot(self) -> dict[str, float]:
        """Return a summary dict for logging / dashboards."""
        return {
            "count": float(self.count),
            "mean": self.mean,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "half_life_h": self.half_life_h(),
            "autocorr_1": self.autocorrelation(1),
        }
