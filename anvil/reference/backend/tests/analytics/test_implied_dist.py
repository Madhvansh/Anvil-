"""Implied distribution: expected-move formula, straddle, and a normalized RND."""

from __future__ import annotations

import math

import pytest

from oip.analytics.implied_dist import implied_distribution
from oip.analytics.util import chain_t_years

pytestmark = [pytest.mark.unit]


def test_expected_move_atm_iv_formula(wide_chain):
    d = implied_distribution(wide_chain)
    t = chain_t_years(wide_chain)
    assert d.atm_iv is not None
    assert d.em_atm_iv == pytest.approx(wide_chain.future_price * d.atm_iv * math.sqrt(t), rel=1e-9)


def test_em_straddle_positive(wide_chain):
    d = implied_distribution(wide_chain)
    assert d.em_straddle is not None and d.em_straddle > 0


def test_rnd_normalizes_and_brackets_probability(wide_chain):
    d = implied_distribution(wide_chain)
    assert len(d.density) >= 3
    mass = sum(pdf * w for (_, pdf), w in zip(d.density, d._widths, strict=True))
    assert mass == pytest.approx(1.0, abs=1e-6)
    F = wide_chain.future_price
    assert d.prob_above(0.0) == pytest.approx(1.0, abs=1e-6)
    assert d.prob_above(1e9) == pytest.approx(0.0, abs=1e-6)
    assert 0.0 < d.prob_above(F) < 1.0
    # prob_inside the whole grid is ~1; a tight band around F is between 0 and 1
    assert 0.0 < d.prob_inside(F - 100, F + 100) < 1.0


def test_runs_on_thin_chain(sample_chain):
    d = implied_distribution(sample_chain)
    assert isinstance(d.em_atm_iv, float)
    assert d.needs_real_world_calibration is True
