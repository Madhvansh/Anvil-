"""Calibration scoring: known-value Brier/log-loss, reliability bins, coverage."""

from __future__ import annotations

import pytest

from oip.calibration import scoring

pytestmark = [pytest.mark.unit]


def test_brier_known_values():
    assert scoring.brier_score([(1.0, 1), (0.0, 0)]) == pytest.approx(0.0)   # perfect
    assert scoring.brier_score([(0.0, 1), (1.0, 0)]) == pytest.approx(1.0)   # worst
    assert scoring.brier_score([(0.5, 1), (0.5, 0)]) == pytest.approx(0.25)  # always-50%
    assert scoring.brier_score([]) is None


def test_log_loss_perfect_is_small():
    ll = scoring.log_loss([(0.999999, 1), (0.000001, 0)])
    assert ll is not None and ll < 1e-3


def test_reliability_bins_match_observed():
    pairs = [(0.7, 1)] * 7 + [(0.7, 0)] * 3  # stated 70%, observed 70%
    bins = scoring.reliability_bins(pairs, n_bins=10)
    b = next(b for b in bins if b.lo <= 0.7 < b.hi)
    assert b.n == 10
    assert b.mean_predicted == pytest.approx(0.7)
    assert b.observed_freq == pytest.approx(0.7)


def test_coverage():
    assert scoring.coverage([(0, 10, 5), (0, 10, 11), (0, 10, 3)]) == pytest.approx(2 / 3)
    assert scoring.coverage([]) is None
