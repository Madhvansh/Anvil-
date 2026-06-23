"""Factor library: deterministic firing on the demo chain + a clean, explainable signal payload."""

from anvil.factors import FACTORS, compute_factors, fired_names
from anvil.factors.base import CONFIRMATION, STRONG
from anvil.ingest.demo import build_demo_chain
from anvil.strategy import SignalContext


def _ctx(spot: float = 24000.0) -> SignalContext:
    return SignalContext(build_demo_chain("NIFTY", spot=spot))


def test_factors_registered():
    # the v1 index-options roster is present
    for name in ("gex_regime", "iv_rank_extreme", "event_iv_crush", "expiry_gamma",
                 "oi_gex_confluence", "directional_drift", "pcr_confirmation"):
        assert name in FACTORS


def test_compute_factors_runs_and_is_explainable():
    sigs = compute_factors(_ctx())
    assert sigs
    by_name = {s.name: s for s in sigs}
    assert "gex_regime" in by_name
    for s in sigs:
        assert s.edge_tier in (STRONG, CONFIRMATION)
        assert 0.0 <= s.strength <= 1.0
        d = s.to_dict()
        assert d["name"] == s.name and "active" in d


def test_gex_regime_fires_on_positive_gamma_demo():
    by_name = {s.name: s for s in compute_factors(_ctx())}
    gex = by_name["gex_regime"]
    # the demo NIFTY chain is a positive-gamma / mean-revert tape (see test_strategy)
    assert gex.fired
    assert gex.direction == "short_vol"


def test_fired_names_are_a_subset_of_active_signals():
    sigs = compute_factors(_ctx())
    names = fired_names(sigs)
    assert set(names) == {s.name for s in sigs if s.active}
    assert all(s.fired and s.regime_mask for s in sigs if s.name in names)
