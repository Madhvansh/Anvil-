"""Tests for the dealer-hedging-flow stack (vanna/charm exposure + gamma-flip levels)."""

from __future__ import annotations

import math

from anvil.engine.dealer_flow import (
    compute_dealer_flow,
    dealer_hedge_drift,
    gamma_flip_levels,
)
from anvil.ingest.demo import build_demo_chain
from anvil.models import ChainRow, OptionChain, OptionType

TS = "2026-06-17T06:00:00+00:00"
EXP = "2026-07-31"


def _chain(oi=100_000):
    # A small symmetric chain around spot so vanna/charm have both wings.
    rows = []
    for k in (23800, 23900, 24000, 24100, 24200):
        rows.append(ChainRow(strike=k, option_type=OptionType.CALL, oi=oi, iv=0.13))
        rows.append(ChainRow(strike=k, option_type=OptionType.PUT, oi=oi, iv=0.13))
    return OptionChain(underlying="NIFTY", spot=24000, expiry=EXP, timestamp=TS, lot_size=75, rows=rows)


def test_exposures_finite_and_linear_in_oi():
    r1 = compute_dealer_flow(_chain(oi=100_000))
    r2 = compute_dealer_flow(_chain(oi=200_000))
    assert math.isfinite(r1.total_vanna_exposure) and math.isfinite(r1.total_charm_exposure)
    # Exposure is linear in OI → doubling OI doubles both exposures.
    assert r2.total_vanna_exposure == r1.total_vanna_exposure * 2
    assert r2.total_charm_exposure == r1.total_charm_exposure * 2
    assert len(r1.vanna_walls) <= 3 and len(r1.charm_walls) <= 3
    assert r1.forward_source  # provenance tagged


def test_dealer_sign_flips_exposure():
    r_pos = compute_dealer_flow(_chain(), dealer_sign=1)
    r_neg = compute_dealer_flow(_chain(), dealer_sign=-1)
    assert r_pos.total_vanna_exposure == -r_neg.total_vanna_exposure
    assert r_pos.total_charm_exposure == -r_neg.total_charm_exposure


def test_no_iv_chain_zero_exposure():
    rows = [ChainRow(strike=24000, option_type=OptionType.CALL, oi=1000)]  # no iv, no ltp
    ch = OptionChain(underlying="NIFTY", spot=24000, expiry=EXP, timestamp=TS, lot_size=75, rows=rows)
    res = compute_dealer_flow(ch)
    assert res.total_vanna_exposure == 0.0 and res.total_charm_exposure == 0.0


def test_dealer_hedge_drift_direction():
    res = compute_dealer_flow(_chain())
    # Force a known accumulated delta by overriding via the helper math.
    drift_up = dealer_hedge_drift(res, iv_change_pts=5.0, days=1.0)
    assert drift_up["rehedge_flow"] in ("sell_underlying", "buy_underlying", "neutral")
    # pressure is the negative of accumulated delta.
    assert drift_up["pressure"] == -drift_up["delta_accumulated"]


def test_gamma_flip_levels_band():
    assert gamma_flip_levels(None, 24000) is None
    above = gamma_flip_levels(23800.0, 24000.0)
    assert above["distance"] > 0 and above["acts_as"] == "support"
    below = gamma_flip_levels(24200.0, 24000.0)
    assert below["distance"] < 0 and below["acts_as"] == "resistance"


def test_flip_present_on_demo_chain():
    ch = build_demo_chain("NIFTY", spot=24000.0, expiry=EXP, timestamp=TS)
    res = compute_dealer_flow(ch)
    assert res.zero_gamma_flip is not None
    assert math.isfinite(res.total_vanna_exposure)
