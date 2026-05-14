from __future__ import annotations

import msgspec

from src.models.market import Exchange

# Funding periods per year for an 8-hour interval
_PERIODS_PER_YEAR = 365 * 24 / 8  # 1095.0


class BasisSnapshot(msgspec.Struct, frozen=True, gc=False):
    """
    Instantaneous basis metrics for one symbol on one exchange.
    Basis = (perp_mid - spot_mid) / spot_mid
    Published to bus at: "basis.{exchange}.{symbol}"
    """
    exchange: Exchange
    symbol: str

    spot_mid: float
    perp_mid: float

    basis: float                # dimensionless ratio, e.g. 0.0012 = 0.12%
    basis_bps: float            # basis * 10_000
    annualized_basis: float     # basis * 1095  (decimal, not percent)

    perp_premium: float         # perp_mid - spot_mid (USD)

    funding_rate: float         # current 8h rate (0.0001 = 0.01%)
    predicted_funding: float
    funding_yield_ann: float    # annualized funding rate

    ts_ms: int

    @property
    def is_positive_carry(self) -> bool:
        """True when both basis and funding favor long-spot/short-perp carry."""
        return self.basis > 0 and self.funding_rate > 0

    @property
    def carry_score(self) -> float:
        """
        Simple carry attractiveness score (higher = better entry).
        Combines funding yield and current basis premium.
        """
        return self.funding_yield_ann + self.annualized_basis


class CarryMetrics(msgspec.Struct, frozen=True, gc=False):
    """
    Risk-adjusted carry metrics for a long-spot/short-perp position.
    Published to bus at: "carry.{exchange}.{symbol}"
    """
    exchange: Exchange
    symbol: str

    funding_yield_ann: float         # annualized recurring funding income
    basis_bps: float                 # current basis in bps (entry premium snapshot)

    # Long spot / short perp carry decomposition
    gross_carry_ann: float           # funding_yield_ann + annualized_basis
    gross_carry_bps_ann: float       # * 10_000

    # Estimated round-trip cost (maker+taker fees, annualized by holding period)
    estimated_cost_ann: float
    net_carry_ann: float             # gross - estimated_cost
    net_carry_bps_ann: float

    holding_period_h: float          # assumption used for cost annualization
    ts_ms: int

    @property
    def is_viable(self) -> bool:
        """Net carry > 5% annualized is a meaningful trade."""
        return self.net_carry_ann > 0.05


class MeanReversionSignal(msgspec.Struct, frozen=True, gc=False):
    """
    Statistical mean-reversion signal on basis.
    Published to bus at: "signal.{exchange}.{symbol}"
    Only published when is_signal=True.
    """
    exchange: Exchange
    symbol: str

    basis_current: float
    basis_mean: float
    basis_std: float

    z_score: float
    half_life_h: float          # estimated half-life of mean reversion (hours)

    is_signal: bool
    direction: str              # "long_carry" | "short_carry" | "none"
    signal_strength: float      # |z_score| / threshold  (1.0 = at threshold)

    ts_ms: int
