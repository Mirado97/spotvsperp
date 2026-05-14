from __future__ import annotations

import pytest

from src.funding.history import (
    ACCEL_THRESHOLD,
    EXTREME_THRESHOLD,
    TYPICAL_RATE,
    FundingHistory,
)


def _h(rates: list[float], window: int = 168) -> FundingHistory:
    h = FundingHistory(window=window, ewma_span=8)
    for i, r in enumerate(rates):
        h.push(r, i * 8 * 3_600_000)
    return h


# ── Basic state ───────────────────────────────────────────────────────────────

def test_empty_history():
    h = FundingHistory()
    assert h.count == 0
    assert not h.is_ready
    assert h.mean == 0.0
    assert h.std == 0.0
    assert h.ewma == 0.0
    assert h.acceleration == 0.0
    assert h.extreme_streak == 0


def test_count_and_window():
    h = FundingHistory(window=5)
    for v in range(8):
        h.push(float(v), v)
    assert h.count == 5


def test_is_ready_after_three():
    h = FundingHistory()
    for v in [0.0001, 0.0002]:
        h.push(v, 0)
    assert not h.is_ready
    h.push(0.0003, 0)
    assert h.is_ready


# ── Statistics ────────────────────────────────────────────────────────────────

def test_mean():
    h = _h([0.0001, 0.0002, 0.0003])
    assert h.mean == pytest.approx(0.0002)


def test_std():
    import numpy as np
    rates = [0.0001, 0.0002, 0.0003, 0.0004]
    h = _h(rates)
    expected = float(np.std(rates, ddof=1))
    assert h.std == pytest.approx(expected)


def test_ewma_weights_recent_more():
    # Rates start at 0.0001, then jump to 0.001
    h = _h([0.0001] * 20 + [0.001] * 5)
    # EWMA should be between old mean and new value, closer to new
    assert h.mean < h.ewma  # ewma closer to recent value


def test_ewma_constant_series():
    h = _h([0.0002] * 20)
    assert h.ewma == pytest.approx(0.0002, rel=1e-6)


# ── Acceleration ──────────────────────────────────────────────────────────────

def test_acceleration_rising():
    h = _h([0.0001, 0.0002, 0.0004])
    # last - prev = 0.0004 - 0.0002 = 0.0002
    assert h.acceleration == pytest.approx(0.0002)


def test_acceleration_falling():
    h = _h([0.0004, 0.0003, 0.0001])
    assert h.acceleration == pytest.approx(-0.0002)


def test_acceleration_stable():
    h = _h([0.0001, 0.0001, 0.0001])
    assert h.acceleration == pytest.approx(0.0)
    assert h.acceleration_direction == "stable"
    assert not h.is_accelerating


def test_acceleration_direction_rising():
    h = _h([0.0001, 0.0001 + ACCEL_THRESHOLD * 2])
    assert h.acceleration_direction == "rising"
    assert h.is_accelerating


def test_acceleration_direction_falling():
    h = _h([0.0001 + ACCEL_THRESHOLD * 2, 0.0001])
    assert h.acceleration_direction == "falling"
    assert h.is_accelerating


# ── Regime ────────────────────────────────────────────────────────────────────

def test_regime_neutral():
    h = _h([0.00005] * 20)
    assert h.regime == "neutral"


def test_regime_mildly_bullish():
    h = _h([TYPICAL_RATE * 1.5] * 20)
    assert h.regime == "mildly_bullish"


def test_regime_strongly_bullish():
    h = _h([EXTREME_THRESHOLD * 2] * 20)
    assert h.regime == "strongly_bullish"


def test_regime_strongly_bearish():
    h = _h([-EXTREME_THRESHOLD * 2] * 20)
    assert h.regime == "strongly_bearish"


def test_regime_mildly_bearish():
    h = _h([-TYPICAL_RATE * 1.5] * 20)
    assert h.regime == "mildly_bearish"


# ── Extreme streak ────────────────────────────────────────────────────────────

def test_extreme_streak_increments():
    h = FundingHistory()
    h.push(EXTREME_THRESHOLD * 2, 0)
    h.push(EXTREME_THRESHOLD * 2, 1)
    h.push(EXTREME_THRESHOLD * 2, 2)
    assert h.extreme_streak == 3


def test_extreme_streak_resets():
    h = FundingHistory()
    h.push(EXTREME_THRESHOLD * 2, 0)
    h.push(EXTREME_THRESHOLD * 2, 1)
    h.push(0.0001, 2)  # normal rate → resets
    assert h.extreme_streak == 0


def test_no_streak_for_normal_rates():
    h = _h([0.0001, 0.0002, 0.0001])
    assert h.extreme_streak == 0


# ── Z-score and percentile ────────────────────────────────────────────────────

def test_z_score_at_mean():
    h = _h([0.0001] * 20 + [0.0002] * 20)
    assert h.z_score(h.mean) == pytest.approx(0.0, abs=1e-10)


def test_z_score_zero_std():
    h = _h([0.0001] * 10)
    assert h.z_score(0.0005) == 0.0


def test_percentile_all_below():
    h = _h([0.0001] * 10)
    assert h.percentile_of(0.001) == pytest.approx(1.0)


def test_percentile_all_above():
    h = _h([0.001] * 10)
    assert h.percentile_of(0.0001) == pytest.approx(0.0)


# ── Confidence interval ───────────────────────────────────────────────────────

def test_ci_contains_mean():
    rates = [0.0001 * (i % 5 + 1) for i in range(30)]
    h = _h(rates)
    lo, hi = h.confidence_interval()
    assert lo <= h.mean <= hi


def test_ci_short_history_uses_normal():
    h = _h([0.0001, 0.0002, 0.0003])
    lo, hi = h.confidence_interval()
    # Should not raise; result is approximate
    assert lo < hi


# ── Predicted_next ────────────────────────────────────────────────────────────

def test_predicted_next_before_ready():
    h = FundingHistory()
    h.push(0.0001, 0)
    assert h.predicted_next(0.00015) == pytest.approx(0.00015)


def test_predicted_next_blends():
    rates = [0.0001] * 20
    h = _h(rates)
    # EWMA ≈ mean ≈ exchange prediction ≈ 0.0001
    result = h.predicted_next(0.0001)
    assert result == pytest.approx(0.0001, rel=1e-4)


def test_predicted_next_respects_momentum():
    # Rising funding: each rate higher than previous
    rates = [0.0001 * (1 + i * 0.1) for i in range(20)]
    h = _h(rates)
    # With positive acceleration, predicted_next > ewma
    assert h.predicted_next(h.ewma + h.acceleration) >= h.ewma


# ── Carry metrics ─────────────────────────────────────────────────────────────

def test_annualized_carry():
    h = _h([0.0001] * 20)
    assert h.annualized_carry() == pytest.approx(0.0001 * 1095)


def test_daily_carry():
    h = _h([0.0001] * 20)
    assert h.daily_carry() == pytest.approx(0.0001 * 3)


def test_snapshot_has_required_keys():
    h = _h([0.0001] * 20)
    snap = h.snapshot()
    for key in ("count", "mean", "std", "ewma", "acceleration",
                "extreme_streak", "annualized_carry", "ci_lower", "ci_upper"):
        assert key in snap
