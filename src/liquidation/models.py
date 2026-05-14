from __future__ import annotations

import msgspec

from src.models.market import Exchange

# ── Thresholds ────────────────────────────────────────────────────────────────

SQUEEZE_THRESHOLD: float = 0.7        # |net_pressure| > 0.7 → squeeze
CASCADE_THRESHOLD_USD: float = 1_000_000.0   # USD/min within window → cascade
OI_SPIKE_THRESHOLD: float = 0.05      # 5% OI change vs rolling mean → spike


class LiquidationAlert(msgspec.Struct, frozen=True, gc=False):
    """
    Aggregated liquidation analysis for one symbol over a rolling window.
    Published to bus at: "liq_alert.{exchange}.{symbol}"
    """
    exchange: Exchange
    symbol: str
    window_ms: int

    # ── Liquidation flow ─────────────────────────────────────────────────────
    long_liq_usd: float      # long positions liquidated in window
    short_liq_usd: float     # short positions liquidated in window
    total_liq_usd: float
    net_pressure: float      # [-1, 1]; +1 = all longs liquidated (short squeeze)
    squeeze_side: str        # "long_squeeze" | "short_squeeze" | "neutral"
    is_cascade: bool         # liq_rate_per_min >= CASCADE_THRESHOLD_USD
    liq_rate_per_min: float  # USD/min over window
    event_count: int

    # ── Open interest ─────────────────────────────────────────────────────────
    oi_value: float          # latest OI in USD (0 if not yet received)
    oi_change_pct: float     # (latest - rolling_mean) / rolling_mean
    is_oi_spike: bool        # |oi_change_pct| >= OI_SPIKE_THRESHOLD

    ts_ms: int

    @property
    def is_long_squeeze(self) -> bool:
        return self.squeeze_side == "long_squeeze"

    @property
    def is_short_squeeze(self) -> bool:
        return self.squeeze_side == "short_squeeze"

    @property
    def is_significant(self) -> bool:
        """Any actionable condition: cascade, squeeze, or OI spike."""
        return self.is_cascade or self.squeeze_side != "neutral" or self.is_oi_spike
