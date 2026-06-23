"""Tests for the dealer-flow factors (gamma-flip S/R, charm pin, vanna drift) — abstain-safe + firing."""

from __future__ import annotations

from anvil.factors.dealer_flow import charm_pin, gamma_flip_sr, vanna_drift
from anvil.strategy.types import BEARISH, BULLISH, NEUTRAL


class _DF:
    def __init__(self, *, flip=None, charm_walls=None, vanna=0.0, charm=0.0):
        self.zero_gamma_flip = flip
        self.charm_walls = charm_walls or []
        self.total_vanna_exposure = vanna
        self.total_charm_exposure = charm


class _Ctx:
    def __init__(self, *, dealer_flow=None, spot=100.0, T=0.01, flow=None):
        self.dealer_flow = dealer_flow
        self.spot = spot
        self.T = T
        self.flow = flow


class _Flow:
    def __init__(self, iv_rank=None):
        self.iv_rank = iv_rank


# --- abstain-safe (no data) ------------------------------------------------- #
def test_all_abstain_without_dealer_flow():
    ctx = _Ctx(dealer_flow=None)
    for f in (gamma_flip_sr, charm_pin, vanna_drift):
        sig = f(ctx)
        assert sig.fired is False and sig.edge_tier == "confirmation"


# --- gamma-flip S/R --------------------------------------------------------- #
def test_gamma_flip_sr_fires_near_flip():
    ctx = _Ctx(dealer_flow=_DF(flip=100.0), spot=100.0)   # spot == flip → distance 0
    sig = gamma_flip_sr(ctx)
    assert sig.fired and sig.direction == NEUTRAL and sig.strength > 0.9
    assert sig.drivers["acts_as"] in ("support", "resistance")


def test_gamma_flip_sr_abstains_far_from_flip():
    ctx = _Ctx(dealer_flow=_DF(flip=80.0), spot=100.0)    # 20% away → no S/R
    assert gamma_flip_sr(ctx).fired is False


# --- charm pin -------------------------------------------------------------- #
def test_charm_pin_fires_near_expiry_and_strike():
    ctx = _Ctx(dealer_flow=_DF(charm_walls=[(100.0, 5000.0)]), spot=100.0, T=1.0 / 365.0)
    sig = charm_pin(ctx)
    assert sig.fired and sig.direction == NEUTRAL
    assert sig.drivers["pin_strike"] == 100.0


def test_charm_pin_abstains_far_from_expiry():
    ctx = _Ctx(dealer_flow=_DF(charm_walls=[(100.0, 5000.0)]), spot=100.0, T=30.0 / 365.0)
    assert charm_pin(ctx).fired is False


# --- vanna drift (couples dealer vanna with IV-rank velocity) ---------------- #
def test_vanna_drift_bearish_when_positive_delta_accum():
    # +vanna × +IV move → +delta accumulated → dealers SELL → bearish pressure
    ctx = _Ctx(dealer_flow=_DF(vanna=100.0), flow=_Flow(iv_rank={"change_points": 5.0}))
    sig = vanna_drift(ctx)
    assert sig.fired and sig.direction == BEARISH and 0.0 < sig.strength <= 0.6


def test_vanna_drift_bullish_when_negative_delta_accum():
    ctx = _Ctx(dealer_flow=_DF(vanna=100.0), flow=_Flow(iv_rank={"change_points": -5.0}))
    sig = vanna_drift(ctx)
    assert sig.fired and sig.direction == BULLISH


def test_vanna_drift_abstains_without_iv_velocity():
    ctx = _Ctx(dealer_flow=_DF(vanna=100.0), flow=None)
    assert vanna_drift(ctx).fired is False
