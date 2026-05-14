from __future__ import annotations

import dataclasses

from src.models.market import InstrumentType
from src.models.orders import Fill, OrderSide

_EPS = 1e-12


@dataclasses.dataclass
class SymbolState:
    """Per-symbol position state for delta tracking."""
    spot_qty: float = 0.0          # net spot position (positive = long)
    perp_qty: float = 0.0          # net perp position (negative = short)
    spot_avg_price: float = 0.0
    perp_avg_price: float = 0.0
    mark_price: float = 0.0        # latest mid from ticker

    @property
    def net_delta(self) -> float:
        """Net delta in base currency. 0 = delta-neutral."""
        return self.spot_qty + self.perp_qty

    @property
    def net_delta_usd(self) -> float:
        return self.net_delta * self.mark_price if self.mark_price > 0 else 0.0

    @property
    def exposure_usd(self) -> float:
        """Two-sided exposure: (|spot| + |perp|) / 2 * price."""
        if self.mark_price <= 0:
            return 0.0
        return (abs(self.spot_qty) + abs(self.perp_qty)) / 2.0 * self.mark_price


class DeltaTracker:
    """
    Maintains per-symbol position state updated from Fill events.
    Tracks spot vs. perp legs separately for delta-neutral monitoring.
    """

    def __init__(self) -> None:
        self._positions: dict[str, SymbolState] = {}

    # ── Mutations ─────────────────────────────────────────────────────────────

    def on_fill(self, fill: Fill) -> None:
        state = self._ensure(fill.symbol)
        sign = 1.0 if fill.side == OrderSide.BUY else -1.0

        if fill.instrument_type == InstrumentType.SPOT:
            old_qty = state.spot_qty
            if sign > 0 and old_qty >= 0:
                state.spot_avg_price = _wavg(old_qty, state.spot_avg_price, fill.qty, fill.price)
            state.spot_qty = old_qty + sign * fill.qty
        else:  # PERPETUAL / FUTURES
            old_qty = state.perp_qty
            if sign > 0 and old_qty >= 0:
                state.perp_avg_price = _wavg(old_qty, state.perp_avg_price, fill.qty, fill.price)
            state.perp_qty = old_qty + sign * fill.qty

    def on_price(self, symbol: str, mark_price: float) -> None:
        self._ensure(symbol).mark_price = mark_price

    # ── Queries ───────────────────────────────────────────────────────────────

    def net_delta(self, symbol: str) -> float:
        s = self._positions.get(symbol)
        return s.net_delta if s else 0.0

    def net_delta_usd(self, symbol: str) -> float:
        s = self._positions.get(symbol)
        return s.net_delta_usd if s else 0.0

    def total_exposure_usd(self) -> float:
        return sum(s.exposure_usd for s in self._positions.values())

    def max_delta_usd_symbol(self) -> tuple[str, float]:
        """Returns (symbol, |net_delta_usd|) for the worst-case symbol."""
        if not self._positions:
            return "", 0.0
        sym, state = max(
            self._positions.items(),
            key=lambda kv: abs(kv[1].net_delta_usd),
        )
        return sym, abs(state.net_delta_usd)

    def position(self, symbol: str) -> SymbolState | None:
        return self._positions.get(symbol)

    def all_symbols(self) -> list[str]:
        return list(self._positions.keys())

    # ── Internal ──────────────────────────────────────────────────────────────

    def _ensure(self, symbol: str) -> SymbolState:
        if symbol not in self._positions:
            self._positions[symbol] = SymbolState()
        return self._positions[symbol]


def _wavg(old_qty: float, old_price: float, add_qty: float, add_price: float) -> float:
    total = old_qty + add_qty
    if total < _EPS:
        return add_price
    return (old_qty * old_price + add_qty * add_price) / total
