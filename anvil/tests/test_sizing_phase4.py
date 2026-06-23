"""Phase 4 honest-sizing safeguards (strategy/sizing.size_units).

Each new term is OFF unless its per-call input is supplied, so the no-op equivalence test pins the
backward-compatibility invariant; the rest prove each safeguard binds and is reported.
"""

from anvil.strategy.generate import GenConfig
from anvil.strategy.sizing import SizingConfig, kelly_fraction_star, shrink_edge, size_units
from anvil.tips.equities import _sizing

BASE = dict(risk_fraction=0.05, kelly_fraction=0.55, max_exposure_pct=0.40, max_lots_per_underlying=20)
# A high-cap profile so the Kelly term (not the lot cap) binds, exposing payoff/edge effects on units.
UNCAPPED = dict(risk_fraction=0.9, kelly_fraction=0.55, max_exposure_pct=0.9, max_lots_per_underlying=100_000)


def test_no_op_equivalence_when_no_kwargs():
    cfg = SizingConfig(**BASE)
    units, info = size_units(2_000.0, 0.60, 2_000.0, 1_000_000.0, cfg)
    # Pre-Phase-4 behaviour: min(by_risk=25, by_kelly=55, by_exposure=200, lot_cap=20) -> 20.
    assert units == 20
    assert info["binding"] == "lot_cap"
    # No new term reported unless activated.
    for k in ("units_by_cvar", "units_by_margin", "edge_shrunk", "cost_per_unit"):
        assert k not in info
    # from_settings carries live knobs, but with NO kwargs it is still a no-op (lot cap binds at 20).
    u2, _ = size_units(2_000.0, 0.60, 2_000.0, 1_000_000.0, SizingConfig.from_settings())
    assert u2 == 20


def test_sizing_config_unified_across_engines():
    # The two former construction sites now share one factory -> identical config.
    assert GenConfig.from_settings().sizing == _sizing()
    fs = SizingConfig.from_settings()
    assert fs.default_payoff_ratio == 1.5
    assert fs.short_vol_kelly_cap <= fs.kelly_fraction  # the cap is a real cap


def test_edge_shrink_monotone_and_endpoints():
    z = 1.0
    assert shrink_edge(0.60, None, z) == 0.60   # OFF when n is None
    assert shrink_edge(0.60, 0, z) == 0.5        # unmeasured edge -> fully shrunk
    s50, s400 = shrink_edge(0.60, 50, z), shrink_edge(0.60, 400, z)
    assert 0.5 < s50 < s400 < 0.60               # haircut relaxes as evidence grows
    assert abs(s50 - 0.531) < 0.005
    # Below-0.5 edges are pulled UP toward 0.5 (shrink is symmetric about the no-edge point).
    assert 0.40 < shrink_edge(0.40, 50, z) < 0.50


def test_unmeasured_edge_cannot_be_kelly_sized():
    cfg = SizingConfig(**BASE, edge_shrink_z=1.0)
    u, info = size_units(2_000.0, 0.60, 2_000.0, 1_000_000.0, cfg, edge_n=0)
    assert info["edge_shrunk"] == 0.5 and info["edge_n"] == 0
    assert info["units_by_kelly"] == 0 and u == 0


def test_cvar_cap_binds_and_reports():
    cfg = SizingConfig(**BASE, cvar_budget_pct=0.08)
    # Generous risk/kelly/exposure (small max_loss) but a fat per-unit tail.
    u, info = size_units(1_000.0, 0.60, 2_000.0, 1_000_000.0, cfg, cvar_per_unit=20_000.0)
    assert info["units_by_cvar"] == 4  # 0.08 * 1e6 / 20_000
    assert info["binding"] == "cvar" and u == 4


def test_cvar_term_off_without_budget():
    cfg = SizingConfig(**BASE)  # cvar_budget_pct default 0.0 -> term off even if a cvar is passed
    _, info = size_units(1_000.0, 0.60, 2_000.0, 1_000_000.0, cfg, cvar_per_unit=20_000.0)
    assert "units_by_cvar" not in info


def test_cost_adjusted_payoff_lowers_kelly():
    cfg = SizingConfig(**UNCAPPED)
    gross_u, gi = size_units(2_000.0, 0.60, 3_000.0, 1_000_000.0, cfg)
    net_u, ni = size_units(2_000.0, 0.60, 3_000.0, 1_000_000.0, cfg, cost_per_unit=500.0)
    assert ni["payoff_ratio"] < gi["payoff_ratio"]
    assert ni["kelly_f_star"] < gi["kelly_f_star"]
    assert net_u < gross_u  # netting cost out of the win shrinks the Kelly bet


def test_margin_cap_binds_and_reports():
    cfg = SizingConfig(**BASE)
    u, info = size_units(1_000.0, 0.60, 2_000.0, 1_000_000.0, cfg, required_margin_per_unit=100_000.0)
    assert info["units_by_margin"] == 4  # buying power 0.40*1e6 / 100_000
    assert info["binding"] == "margin" and u == 4


def test_short_vol_kelly_cap():
    cfg = SizingConfig(**UNCAPPED, short_vol_kelly_cap=0.10)
    base_u, bi = size_units(2_000.0, 0.60, 3_000.0, 1_000_000.0, cfg)  # no regime -> full Kelly
    sv_u, si = size_units(2_000.0, 0.60, 3_000.0, 1_000_000.0, cfg, regime_kind="short_vol")
    assert bi["kelly_fraction_used"] == 0.55
    assert si["kelly_fraction_used"] == 0.10
    assert sv_u < base_u


def test_kelly_fraction_star_unchanged():
    assert abs(kelly_fraction_star(0.60, 2.0) - 0.40) < 1e-9
    assert kelly_fraction_star(0.40, 0.5) == 0.0
