"""Tests for the anti-overfit signal-admission gate (decorrelation + incremental edge + shrinkage)."""

from __future__ import annotations

import numpy as np

from anvil.backtest import orthogonality as orth


def test_pearson_and_mi():
    x = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert orth.pearson(x, x) == 1.0
    assert orth.pearson(x, [5, 4, 3, 2, 1]) == -1.0
    assert orth.pearson(x, [1, 1, 1, 1, 1]) is None     # constant → undefined
    assert orth.gaussian_mutual_information(x, [1, 1, 1, 1, 1]) is None
    assert orth.gaussian_mutual_information(x, x) > 5.0  # identical → very high MI


def test_residual_information_fraction():
    rng = np.random.default_rng(0)
    a = rng.normal(size=200)
    b = rng.normal(size=200)
    # Orthogonal random signal → most variance is new.
    assert orth.residual_information_fraction(a, [b]) > 0.8
    # A linear combination of incumbents → almost no new information.
    combo = 2.0 * a + 0.5 * b
    assert orth.residual_information_fraction(combo, [a, b]) < 0.05
    # No incumbents → fully orthogonal by definition.
    assert orth.residual_information_fraction(a, []) == 1.0


def test_shrink_toward_prior():
    # Thin sample → pulled hard toward the prior; abundant sample → barely moves.
    thin = orth.shrink_toward_prior(0.10, n=5, prior=0.0, prior_weight=20.0)
    rich = orth.shrink_toward_prior(0.10, n=2000, prior=0.0, prior_weight=20.0)
    assert thin < rich < 0.10
    assert abs(rich - 0.10) < 0.005
    assert thin < 0.03


def test_admit_signal_rejects_redundant():
    rng = np.random.default_rng(1)
    incumbent = rng.normal(size=300)
    duplicate = incumbent.copy() + rng.normal(scale=1e-6, size=300)  # essentially the same signal
    v = orth.admit_signal(duplicate, [incumbent])
    assert not v.admit
    assert any("too_correlated" in r or "redundant" in r for r in v.reasons)


def test_admit_signal_accepts_orthogonal_with_edge():
    rng = np.random.default_rng(2)
    incumbent = rng.normal(size=300)
    candidate = rng.normal(size=300)  # independent
    v = orth.admit_signal(
        candidate, [incumbent],
        edge_with=0.08, edge_without=0.05, n_samples=400,
    )
    assert v.admit
    assert v.shrunk_edge is not None and v.shrunk_edge > 0
    assert "admitted" in v.reasons


def test_admit_signal_rejects_thin_sample_edge():
    rng = np.random.default_rng(3)
    incumbent = rng.normal(size=300)
    candidate = rng.normal(size=300)
    # Orthogonal, but the incremental edge is from a tiny sample → shrinks below the bar → reject.
    v = orth.admit_signal(
        candidate, [incumbent],
        edge_with=0.06, edge_without=0.05, n_samples=3, prior_weight=50.0,
        min_incremental_edge=0.001,
    )
    assert not v.admit
    assert any("no_incremental_edge" in r for r in v.reasons)
    assert v.shrunk_edge < 0.001  # shrinkage killed the thin-sample overconfidence
