"""Tests for the chain-analytics factors (skew slope, OI thrust, smart-money block, 0DTE) — abstain + fire."""

from __future__ import annotations

from types import SimpleNamespace

from anvil.factors.chain_analytics import (
    oi_change_thrust,
    skew_slope_extreme,
    smart_money_block,
    zero_dte_dynamics,
)
from anvil.ingest import get_connector
from anvil.strategy.context import SignalContext
from anvil.strategy.types import BEARISH, BULLISH, NEUTRAL


def _ctx():
    return SignalContext(get_connector("demo").get_chain("NIFTY"), source="test")


def test_all_abstain_without_chain():
    ctx = SimpleNamespace(chain=None, prev_chain=None, T=0.02)
    for f in (skew_slope_extreme, oi_change_thrust, smart_money_block, zero_dte_dynamics):
        assert f(ctx).fired is False


def test_factors_run_on_real_chain():
    ctx = _ctx()
    for f in (skew_slope_extreme, oi_change_thrust, smart_money_block, zero_dte_dynamics):
        sig = f(ctx)
        assert sig.edge_tier == "confirmation"
        assert isinstance(sig.fired, bool)
        assert sig.direction in ("", NEUTRAL, BULLISH, BEARISH)


def test_skew_slope_extreme_fires_on_steep_smile():
    # craft a ctx whose iv_skew_slope returns a steep negative slope
    import anvil.factors.chain_analytics as mod

    ctx = SimpleNamespace(chain=object())
    orig = mod.cd.iv_skew_slope
    mod.cd.iv_skew_slope = lambda chain: {"slope": -1.5, "curvature": 2.0, "atm_iv": 0.15, "n": 9}
    try:
        sig = skew_slope_extreme(ctx)
        assert sig.fired and sig.drivers["side"] == "put_skew" and sig.strength > 0
    finally:
        mod.cd.iv_skew_slope = orig


def test_oi_change_thrust_direction():
    import anvil.factors.chain_analytics as mod

    ctx = SimpleNamespace(chain=object(), prev_chain=None)
    orig = mod.cd.oi_change_bias
    mod.cd.oi_change_bias = lambda chain, prev: {
        "bias": "bullish", "strength": 0.7, "net": 0.7, "call_build": 100.0, "put_build": 900.0}
    try:
        sig = oi_change_thrust(ctx)
        assert sig.fired and sig.direction == BULLISH and sig.strength == 0.7
    finally:
        mod.cd.oi_change_bias = orig


def test_zero_dte_fires_on_expiry_pin():
    import anvil.factors.chain_analytics as mod

    ctx = SimpleNamespace(chain=object(), T=1.0 / 365.0)
    orig = mod.cd.zero_dte_dynamics
    mod.cd.zero_dte_dynamics = lambda chain, T: {
        "dte": 1.0, "is_0dte": True, "is_expiry_week": True, "max_pain": 100.0, "pin_distance": 0.001}
    try:
        sig = zero_dte_dynamics(ctx)
        assert sig.fired and sig.direction == NEUTRAL and sig.drivers["is_0dte"] is True
    finally:
        mod.cd.zero_dte_dynamics = orig
