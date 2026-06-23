"""Breeden-Litzenberger implied distribution sanity checks."""


try:
    from numpy import trapezoid as _trapz
except ImportError:  # numpy < 2.0
    from numpy import trapz as _trapz

from anvil.engine.implied_dist import implied_distribution
from anvil.ingest.demo import build_demo_chain

TS = "2026-06-17T06:00:00+00:00"
EXP = "2026-07-31"


def _dist(**kw):
    ch = build_demo_chain("NIFTY", spot=24000.0, expiry=EXP, timestamp=TS, **kw)
    d = implied_distribution(ch)
    assert d is not None
    return ch, d


def test_density_integrates_to_one():
    _, d = _dist()
    area = float(_trapz(d.density, d.strikes))
    assert abs(area - 1.0) < 1e-6


def test_density_non_negative():
    _, d = _dist()
    assert (d.density >= 0).all()


def test_flat_smile_std_matches_lognormal():
    # With a FLAT IV smile and wide strikes, BL must recover the lognormal width
    # S * sigma * sqrt(T) closely — this isolates the BL math from skew effects.
    ch, d = _dist(n_strikes=80, atm_iv=0.13, skew_slope=0.0, curvature=0.0)
    assert d.em_atm_iv > 0
    rel = abs(d.expected_move_1sigma - d.em_atm_iv) / d.em_atm_iv
    assert rel < 0.10


def test_skewed_smile_std_same_ballpark():
    # The realistic (skewed) demo chain: std should be the same order as the
    # ATM-IV expected move (skew legitimately widens it).
    ch, d = _dist()
    ratio = d.expected_move_1sigma / d.em_atm_iv
    assert 0.5 < ratio < 2.0


def test_prob_within_one_sigma_is_reasonable():
    ch, d = _dist()
    em = d.expected_move_1sigma
    p = d.prob_between(ch.spot - em, ch.spot + em)
    assert 0.5 < p < 0.85  # ~0.68 for a roughly-normal core
