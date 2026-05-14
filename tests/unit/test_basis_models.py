from __future__ import annotations

import msgspec
import pytest

from src.basis.models import BasisSnapshot, CarryMetrics, MeanReversionSignal
from src.models.market import Exchange


def _make_snap(
    basis: float = 0.001,
    funding_rate: float = 0.0001,
    funding_yield_ann: float = 0.1095,
    spot_mid: float = 100_000.0,
) -> BasisSnapshot:
    return BasisSnapshot(
        exchange=Exchange.BYBIT,
        symbol="BTCUSDT",
        spot_mid=spot_mid,
        perp_mid=spot_mid * (1 + basis),
        basis=basis,
        basis_bps=basis * 10_000,
        annualized_basis=basis * 1095,
        perp_premium=spot_mid * basis,
        funding_rate=funding_rate,
        predicted_funding=funding_rate,
        funding_yield_ann=funding_yield_ann,
        ts_ms=1_000,
    )


# ── BasisSnapshot ─────────────────────────────────────────────────────────────

def test_basis_snapshot_is_frozen():
    snap = _make_snap()
    with pytest.raises(AttributeError):
        snap.basis = 0.0  # type: ignore[misc]


def test_positive_carry_detection():
    assert _make_snap(basis=0.001, funding_rate=0.0001).is_positive_carry
    assert not _make_snap(basis=-0.001, funding_rate=0.0001).is_positive_carry
    assert not _make_snap(basis=0.001, funding_rate=-0.0001).is_positive_carry


def test_carry_score():
    snap = _make_snap(basis=0.001, funding_yield_ann=0.1095)
    # annualized_basis = 0.001 * 1095 = 1.095
    # carry_score = 0.1095 + 1.095 = 1.2045
    expected = 0.1095 + 0.001 * 1095
    assert snap.carry_score == pytest.approx(expected, rel=1e-6)


def test_basis_bps_formula():
    snap = _make_snap(basis=0.0012)
    assert snap.basis_bps == pytest.approx(12.0)


def test_annualized_basis_formula():
    snap = _make_snap(basis=0.001)
    assert snap.annualized_basis == pytest.approx(1.095)


def test_perp_premium_formula():
    snap = _make_snap(basis=0.001, spot_mid=100_000.0)
    assert snap.perp_premium == pytest.approx(100.0)  # 100_000 * 0.001


# ── CarryMetrics ──────────────────────────────────────────────────────────────

def test_carry_viable_threshold():
    viable = CarryMetrics(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        funding_yield_ann=0.10, basis_bps=10.0,
        gross_carry_ann=0.15, gross_carry_bps_ann=1500.0,
        estimated_cost_ann=0.02, net_carry_ann=0.13, net_carry_bps_ann=1300.0,
        holding_period_h=168.0, ts_ms=0,
    )
    not_viable = CarryMetrics(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        funding_yield_ann=0.01, basis_bps=2.0,
        gross_carry_ann=0.02, gross_carry_bps_ann=200.0,
        estimated_cost_ann=0.02, net_carry_ann=0.00, net_carry_bps_ann=0.0,
        holding_period_h=168.0, ts_ms=0,
    )
    assert viable.is_viable
    assert not not_viable.is_viable


# ── MeanReversionSignal ───────────────────────────────────────────────────────

def test_signal_direction_long_carry():
    sig = MeanReversionSignal(
        exchange=Exchange.BYBIT, symbol="BTCUSDT",
        basis_current=0.005, basis_mean=0.001, basis_std=0.001,
        z_score=4.0, half_life_h=24.0,
        is_signal=True, direction="long_carry", signal_strength=2.0,
        ts_ms=0,
    )
    assert sig.is_signal
    assert sig.direction == "long_carry"
    assert sig.signal_strength == pytest.approx(2.0)


# ── msgspec round-trip ────────────────────────────────────────────────────────

def test_basis_snapshot_encode_decode():
    snap = _make_snap()
    encoded = msgspec.json.encode(snap)
    decoded = msgspec.json.decode(encoded, type=BasisSnapshot)
    assert decoded.symbol == snap.symbol
    assert decoded.basis == pytest.approx(snap.basis)
    assert decoded.funding_yield_ann == pytest.approx(snap.funding_yield_ann)
