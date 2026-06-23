"""Tests for the momentum factors (registration, firing, regime-mask shape, abstention)."""

from __future__ import annotations

from types import SimpleNamespace

from anvil.engine import flow_momentum as fm
from anvil.engine import momentum as mom
from anvil.factors import compute_factors, momentum as fmom
from anvil.factors.base import FACTORS
from anvil.strategy.types import BULLISH, NEUTRAL, SHORT_VOL


def _ctx(**kw):
    base = dict(momentum=None, flow=None, gex=None, intraday_session=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_all_momentum_factors_registered():
    for name in (fmom.MTF_TREND, fmom.GEX_FLIP, fmom.OI_VELOCITY, fmom.IV_RANK_VEL,
                 fmom.INTRADAY_ORVWAP, fmom.EXPIRY_LAST30):
        assert name in FACTORS


def test_mtf_trend_fires_and_abstains():
    read = mom.MomentumRead(direction=BULLISH, strength=0.6, agreement=3, n_timeframes=3, per_tf={})
    sig = fmom.mtf_trend(_ctx(momentum=read))
    assert sig.fired and sig.direction == BULLISH and sig.strength == 0.6 and sig.edge_tier == "strong"
    # No data → abstain.
    assert not fmom.mtf_trend(_ctx()).fired
    # Conflict (neutral) → abstain.
    neutral = mom.MomentumRead(direction=NEUTRAL, strength=0.0, agreement=0, n_timeframes=2, per_tf={})
    assert not fmom.mtf_trend(_ctx(momentum=neutral)).fired


def test_gex_flip_and_iv_rank_and_oi_factors():
    flow = fm.flow_momentum(
        oi_series=[1e6, 1.1e6, 1.3e6],
        gex_series=[-100.0, -50.0, 20.0],   # flip to positive → SHORT_VOL
        iv_rank_series=[40.0, 50.0, 60.0],  # richer → SHORT_VOL
    )
    ctx = _ctx(flow=flow)
    gex_sig = fmom.gex_flip_momentum(ctx)
    assert gex_sig.fired and gex_sig.direction == SHORT_VOL and gex_sig.edge_tier == "strong"
    oi_sig = fmom.oi_velocity_thrust(ctx)
    assert oi_sig.fired and oi_sig.direction == "" and oi_sig.edge_tier == "confirmation"
    ivr_sig = fmom.iv_rank_velocity(ctx)
    assert ivr_sig.fired and ivr_sig.direction == SHORT_VOL


def test_flow_factors_abstain_without_data():
    ctx = _ctx()
    assert not fmom.gex_flip_momentum(ctx).fired
    assert not fmom.oi_velocity_thrust(ctx).fired
    assert not fmom.iv_rank_velocity(ctx).fired


def test_intraday_or_vwap_factor():
    sess = {"highs": [10.0, 10.5, 10.2, 11.0], "lows": [9.5, 9.8, 9.7, 10.5],
            "prices": [10.0, 10.5, 10.8], "volumes": [1.0, 1.0, 1.0], "last": 10.8, "or_bars": 3}
    sig = fmom.intraday_or_vwap(_ctx(intraday_session=sess))
    assert sig.fired and sig.direction == BULLISH
    assert not fmom.intraday_or_vwap(_ctx()).fired


def test_expiry_last30_gamma_factor():
    sess = {"returns": [0.002, 0.001, 0.0005], "days_to_expiry": 0}
    neg_gamma = _ctx(intraday_session=sess, gex=SimpleNamespace(total_gex=-500.0))
    sig = fmom.expiry_last30_gamma(neg_gamma)
    assert sig.fired and sig.direction == BULLISH
    # Positive gamma → no amplification → abstain.
    pos_gamma = _ctx(intraday_session=sess, gex=SimpleNamespace(total_gex=500.0))
    assert not fmom.expiry_last30_gamma(pos_gamma).fired


def test_compute_factors_includes_momentum():
    read = mom.MomentumRead(direction=BULLISH, strength=0.6, agreement=3, n_timeframes=3, per_tf={})
    sigs = compute_factors(_ctx(momentum=read))
    names = {s.name for s in sigs}
    assert fmom.MTF_TREND in names  # momentum factor flows through the shared runner
