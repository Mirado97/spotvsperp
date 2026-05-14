from __future__ import annotations

import math

import numpy as np
import pytest

from src.basis.history import BasisHistory


def _filled(values: list[float], window: int = 200) -> BasisHistory:
    h = BasisHistory(window=window)
    for v in values:
        h.push(v)
    return h


# ── Basic stats ───────────────────────────────────────────────────────────────

def test_mean():
    h = _filled([1.0, 2.0, 3.0, 4.0, 5.0])
    assert h.mean == pytest.approx(3.0)


def test_std():
    h = _filled([1.0, 2.0, 3.0, 4.0, 5.0])
    expected = float(np.std([1, 2, 3, 4, 5], ddof=1))
    assert h.std == pytest.approx(expected)


def test_min_max():
    h = _filled([3.0, 1.0, 4.0, 2.0, 5.0])
    assert h.min == pytest.approx(1.0)
    assert h.max == pytest.approx(5.0)


def test_empty_stats():
    h = BasisHistory()
    assert h.mean == 0.0
    assert h.std == 0.0
    assert h.count == 0
    assert not h.is_ready


def test_window_evicts_oldest():
    h = BasisHistory(window=3)
    for v in [1.0, 2.0, 3.0, 100.0]:
        h.push(v)
    assert h.count == 3
    assert h.min == pytest.approx(2.0)


# ── Z-score ───────────────────────────────────────────────────────────────────

def test_z_score_at_mean():
    h = _filled([1.0, 2.0, 3.0, 4.0, 5.0])
    assert h.z_score(h.mean) == pytest.approx(0.0)


def test_z_score_one_std_above():
    h = _filled([0.0] * 100 + [1.0] * 100)
    z = h.z_score(h.mean + h.std)
    assert abs(z - 1.0) < 0.01


def test_z_score_zero_std():
    h = _filled([2.0] * 50)
    assert h.z_score(3.0) == 0.0


# ── Percentile ────────────────────────────────────────────────────────────────

def test_percentile_median():
    h = _filled(list(range(1, 101)))  # 1..100
    # Value 50 → 50% of values ≤ 50 → percentile ≈ 0.50
    assert h.percentile(50) == pytest.approx(0.50, abs=0.01)


def test_percentile_max():
    h = _filled([1.0, 2.0, 3.0, 4.0, 5.0])
    assert h.percentile(5.0) == pytest.approx(1.0)


# ── Bollinger bands ───────────────────────────────────────────────────────────

def test_bollinger_bands():
    h = _filled([0.0] * 100)
    lower, mid, upper = h.bollinger_bands(n_std=2.0)
    assert lower == pytest.approx(0.0)
    assert mid == pytest.approx(0.0)
    assert upper == pytest.approx(0.0)


def test_bollinger_bands_nonzero():
    values = [float(i) for i in range(100)]
    h = _filled(values)
    lower, mid, upper = h.bollinger_bands(2.0)
    assert upper > mid > lower
    assert upper - mid == pytest.approx(mid - lower, rel=1e-6)


# ── Half-life ─────────────────────────────────────────────────────────────────

def test_half_life_mean_reverting_series():
    """Synthetic AR(1) with known half-life of ~8 periods (~64h)."""
    rng = np.random.default_rng(42)
    phi = 0.917   # corresponds to half-life ≈ 8 periods
    y = [0.0]
    for _ in range(300):
        y.append(phi * y[-1] + rng.normal(0, 0.0001))
    h = _filled(y[1:])
    hl = h.half_life_h()
    # Should be close to 8*8=64h but noisy; accept wide range
    assert 10 < hl < 200


def test_half_life_random_walk_not_short():
    """Pure random walk has no mean reversion → half-life should be long (>> 24h)."""
    rng = np.random.default_rng(0)
    series = list(np.cumsum(rng.normal(0, 0.001, 100)))
    h = _filled(series)
    hl = h.half_life_h()
    # A random walk is not mean-reverting; any spurious β < 0 should still
    # produce a long half-life (>100h) for a reasonable sample size.
    assert hl == float("inf") or hl > 100


def test_half_life_insufficient_data():
    h = _filled([0.001] * 20)  # below MIN_HALF_LIFE_SAMPLES=30
    assert h.half_life_h() == float("inf")


# ── Autocorrelation ───────────────────────────────────────────────────────────

def test_autocorrelation_constant_series():
    h = _filled([1.0] * 50)
    # All values identical → corr is undefined (nan); handle gracefully
    ac = h.autocorrelation(1)
    assert math.isnan(ac) or ac == pytest.approx(0.0, abs=0.1)


def test_autocorrelation_alternating():
    """Perfect negative autocorrelation at lag 1."""
    series = [1.0, -1.0] * 50
    h = _filled(series)
    ac = h.autocorrelation(1)
    assert ac < -0.9


# ── Snapshot dict ─────────────────────────────────────────────────────────────

def test_snapshot_keys():
    h = _filled([0.001] * 50)
    snap = h.snapshot()
    for key in ("count", "mean", "std", "min", "max", "half_life_h", "autocorr_1"):
        assert key in snap
