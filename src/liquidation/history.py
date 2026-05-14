from __future__ import annotations

from collections import deque

import numpy as np

from src.liquidation.models import (
    CASCADE_THRESHOLD_USD,
    OI_SPIKE_THRESHOLD,
    SQUEEZE_THRESHOLD,
)
from src.models.liquidation import LiquidationEvent

_EPS = 1e-12


class LiquidationHistory:
    """
    Rolling time-window of liquidation events.

    Events older than window_ms are evicted on each push.
    Default window: 5 minutes (300_000 ms).
    """

    def __init__(self, window_ms: int = 300_000) -> None:
        self._window_ms = window_ms
        self._events: deque[LiquidationEvent] = deque()

    def push(self, event: LiquidationEvent) -> None:
        self._events.append(event)
        self._evict(event.ts_ms)

    def _evict(self, now_ms: int) -> None:
        cutoff = now_ms - self._window_ms
        while self._events and self._events[0].ts_ms < cutoff:
            self._events.popleft()

    # ── State ─────────────────────────────────────────────────────────────────

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def window_ms(self) -> int:
        return self._window_ms

    # ── Flow metrics ──────────────────────────────────────────────────────────

    @property
    def long_liq_usd(self) -> float:
        return sum(e.value_usd for e in self._events if e.side == "long")

    @property
    def short_liq_usd(self) -> float:
        return sum(e.value_usd for e in self._events if e.side == "short")

    @property
    def total_liq_usd(self) -> float:
        return sum(e.value_usd for e in self._events)

    @property
    def net_pressure(self) -> float:
        """
        Directional liquidation pressure in [-1, 1].
        +1 = only longs liquidated (bears dominating, long squeeze).
        -1 = only shorts liquidated (bulls dominating, short squeeze).
        """
        total = self.total_liq_usd
        if total < _EPS:
            return 0.0
        return (self.long_liq_usd - self.short_liq_usd) / total

    @property
    def squeeze_side(self) -> str:
        p = self.net_pressure
        if p > SQUEEZE_THRESHOLD:
            return "long_squeeze"
        if p < -SQUEEZE_THRESHOLD:
            return "short_squeeze"
        return "neutral"

    @property
    def liq_rate_per_min(self) -> float:
        """USD liquidated per minute, normalised to window length."""
        if not self._events:
            return 0.0
        window_min = self._window_ms / 60_000.0
        return self.total_liq_usd / window_min

    @property
    def is_cascade(self) -> bool:
        return self.liq_rate_per_min >= CASCADE_THRESHOLD_USD


class OIHistory:
    """
    Rolling window of open-interest (USD value) samples for spike detection.
    Default window: 20 samples.
    """

    def __init__(self, window: int = 20) -> None:
        self._values: deque[float] = deque(maxlen=window)
        self._latest: float = 0.0

    def push(self, oi_value: float) -> None:
        self._values.append(oi_value)
        self._latest = oi_value

    @property
    def latest(self) -> float:
        return self._latest

    @property
    def mean(self) -> float:
        if not self._values:
            return 0.0
        return float(np.mean(self._values))

    @property
    def oi_change_pct(self) -> float:
        """(latest - rolling_mean) / rolling_mean."""
        mean = self.mean
        if mean < _EPS:
            return 0.0
        return (self._latest - mean) / mean

    @property
    def is_spike(self) -> bool:
        return abs(self.oi_change_pct) >= OI_SPIKE_THRESHOLD
