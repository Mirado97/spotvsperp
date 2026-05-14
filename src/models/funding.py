from __future__ import annotations

import msgspec

from src.models.market import Exchange


class FundingRate(msgspec.Struct, frozen=True, gc=False):
    exchange: Exchange
    symbol: str
    rate: float           # e.g. 0.0001 = 0.01% per interval
    predicted: float      # predicted next funding rate
    next_funding_ts: int  # unix ms when next funding settles
    interval_h: int = 8
    ts_ms: int = 0

    @property
    def annualized(self) -> float:
        return self.rate * (365 * 24 / self.interval_h)

    @property
    def daily(self) -> float:
        return self.rate * (24 / self.interval_h)

    @property
    def is_extreme(self) -> bool:
        """Funding > 3x typical (0.01%) threshold."""
        return abs(self.rate) > 0.0003


class FundingSnapshot(msgspec.Struct, frozen=True, gc=False):
    """Rolling stats over the last N funding payments."""
    exchange: Exchange
    symbol: str
    rates: list[float]
    avg_rate: float
    std_rate: float
    min_rate: float
    max_rate: float
    ts_ms: int

    @property
    def annualized_avg(self) -> float:
        return self.avg_rate * (365 * 24 / 8)

    @property
    def regime(self) -> str:
        """Classify funding regime based on average rate."""
        if self.avg_rate > 0.0003:
            return "strongly_long"
        if self.avg_rate > 0.0001:
            return "mildly_long"
        if self.avg_rate < -0.0003:
            return "strongly_short"
        if self.avg_rate < -0.0001:
            return "mildly_short"
        return "neutral"
