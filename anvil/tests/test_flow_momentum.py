"""Unit tests for options-flow momentum (OI/GEX/IV-rank/term velocity)."""

from __future__ import annotations

from anvil.engine import flow_momentum as fm
from anvil.strategy.types import LONG_VOL, NEUTRAL, SHORT_VOL


def test_oi_velocity_building_and_abstain():
    out = fm.oi_velocity([1_000_000, 1_100_000, 1_250_000])
    assert out["building"] and out["fired"] and out["strength"] > 0
    flat = fm.oi_velocity([1_000_000, 1_001_000])
    assert not flat["fired"]
    assert fm.oi_velocity([1_000_000]) is None


def test_gex_velocity_flip_detection():
    flipped = fm.gex_velocity([-100.0, -50.0, 20.0])     # negative → positive cross
    assert flipped["flip"] and flipped["direction"] == SHORT_VOL and not flipped["now_negative_gamma"]
    into_neg = fm.gex_velocity([100.0, 50.0, -20.0])      # positive → negative cross
    assert into_neg["flip"] and into_neg["direction"] == LONG_VOL and into_neg["now_negative_gamma"]
    steady = fm.gex_velocity([100.0, 90.0, 80.0])
    assert not steady["flip"] and steady["direction"] == NEUTRAL
    assert fm.gex_velocity([100.0]) is None


def test_iv_rank_velocity_direction():
    rich = fm.iv_rank_velocity([40.0, 50.0, 60.0])
    assert rich["fired"] and rich["direction"] == SHORT_VOL   # richer premium → sell vol
    cheap = fm.iv_rank_velocity([60.0, 50.0, 40.0])
    assert cheap["fired"] and cheap["direction"] == LONG_VOL  # cheaper → buy vol
    flat = fm.iv_rank_velocity([50.0, 51.0, 52.0])
    assert not flat["fired"]


def test_term_spread_velocity_event_building():
    out = fm.term_spread_velocity([0.0, 0.01, 0.025])
    assert out["backwardation"] and out["steepening"] and out["event_building"]
    flattening = fm.term_spread_velocity([0.03, 0.02, 0.0])
    assert not flattening["event_building"]


def test_flow_momentum_composite_consensus():
    read = fm.flow_momentum(
        oi_series=[1e6, 1.1e6, 1.3e6],
        gex_series=[-100.0, -50.0, 20.0],   # flip to positive → SHORT_VOL
        iv_rank_series=[40.0, 50.0, 60.0],  # richer → SHORT_VOL
        term_spread_series=[0.0, 0.005, 0.01],
    )
    assert read.flip is True
    assert read.vol_direction == SHORT_VOL   # IV-rank + gamma flip agree
    assert read.oi["building"]


def test_flow_momentum_conflict_is_neutral():
    read = fm.flow_momentum(
        gex_series=[-100.0, -50.0, 20.0],   # flip to positive → SHORT_VOL
        iv_rank_series=[60.0, 50.0, 40.0],  # cheaper → LONG_VOL
    )
    assert read.vol_direction == NEUTRAL
    assert "vol_signals_conflict" in read.notes


def test_flow_momentum_empty_degrades_gracefully():
    read = fm.flow_momentum()
    assert read.vol_direction == NEUTRAL and read.oi is None and read.gex is None
