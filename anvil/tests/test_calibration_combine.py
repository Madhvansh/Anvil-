"""Decorrelated combination: whitening (Ledoit–Wolf, no-op below min-n) + no agreement count."""

from __future__ import annotations

import numpy as np

from anvil.calibration.combine import (
    combine_calibrated,
    ledoit_wolf_cov,
    whiten_inputs,
)


def _correlated(n=400, seed=0):
    """Shared-atm_iv-style correlation: col1 and col2 are partly driven by col0 (well-conditioned)."""
    rng = np.random.default_rng(seed)
    a = rng.normal(size=n)
    X = np.column_stack([a, 0.6 * a + 0.8 * rng.normal(size=n), 0.5 * a + 0.9 * rng.normal(size=n)])
    return X


def test_whitening_decorrelates():
    X = _correlated()
    before = abs(np.corrcoef(X.T)[0, 1])
    Xw, info = whiten_inputs(X, min_n=50)
    assert info["applied"] is True
    after = abs(np.corrcoef(Xw.T)[0, 1])
    assert after < before  # off-diagonal correlation collapses
    assert after < 0.1


def test_whitening_noop_below_min_n():
    X = _correlated(n=20)
    Xw, info = whiten_inputs(X, min_n=50)
    assert info["applied"] is False
    assert np.allclose(Xw, X)  # untouched


def test_ledoit_wolf_shrinks_toward_identity():
    X = _correlated()
    S, delta = ledoit_wolf_cov(X)
    assert 0.0 <= delta <= 1.0
    assert S.shape == (3, 3)


def test_combine_is_not_agreement_count():
    # Three identical (perfectly correlated) calibrated probabilities must NOT sum/inflate.
    out = combine_calibrated({"touch": 0.6, "vrp": 0.6, "equity": 0.6})
    assert abs(out - 0.6) < 1e-9  # a single ~0.6, not 1.8 and not an agreement boost


def test_combine_drops_missing_and_handles_empty():
    assert abs(combine_calibrated({"touch": 0.7, "vrp": None}) - 0.7) < 1e-9
    assert combine_calibrated({"touch": None, "vrp": None}) is None


def test_combine_weighted():
    out = combine_calibrated({"a": 0.4, "b": 0.8}, weights={"a": 3.0, "b": 1.0})
    assert abs(out - (3 * 0.4 + 1 * 0.8) / 4.0) < 1e-9
