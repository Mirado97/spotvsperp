from __future__ import annotations

import dataclasses
from enum import IntEnum

import msgspec

from src.models.market import Exchange


class RiskLevel(IntEnum):
    OK        = 0
    WARNING   = 1
    CRITICAL  = 2
    EMERGENCY = 3


@dataclasses.dataclass
class RiskLimits:
    """Configurable per-portfolio risk thresholds."""
    max_delta_usd: float = 5_000.0          # max |net_delta| per symbol in USD
    max_position_usd: float = 50_000.0      # max one-sided position per symbol
    max_total_exposure_usd: float = 200_000.0  # total two-sided exposure across all symbols
    max_drawdown_pct: float = 0.05          # 5% fee-drawdown from initial equity → EMERGENCY
    funding_extreme_streak_limit: int = 6   # consecutive extreme-rate periods → WARNING
    liq_pressure_threshold: float = 0.8    # net_pressure > 0.8 → squeeze WARNING


class RiskAlert(msgspec.Struct, frozen=True, gc=False):
    """
    Published to bus at:
      "risk_alert.{exchange}"       — all alerts
      "emergency_stop.{exchange}"   — EMERGENCY only
    """
    exchange: Exchange
    level: int          # RiskLevel int value
    reason: str         # "delta_exceeded" | "exposure_exceeded" | "drawdown_limit" | ...
    symbol: str         # "" for portfolio-wide checks
    value: float        # triggering metric value
    limit: float        # the limit that was breached or approached
    ts_ms: int

    @property
    def risk_level(self) -> RiskLevel:
        return RiskLevel(self.level)

    @property
    def is_emergency(self) -> bool:
        return self.level >= int(RiskLevel.EMERGENCY)


class RiskSnapshot(msgspec.Struct, frozen=True, gc=False):
    """Point-in-time portfolio risk summary."""
    exchange: Exchange
    total_exposure_usd: float
    max_symbol_delta_usd: float  # worst-case symbol |net_delta_usd|
    worst_symbol: str
    drawdown_pct: float          # cumulative fees / initial_equity
    risk_level: int              # highest active RiskLevel
    is_emergency: bool
    ts_ms: int
