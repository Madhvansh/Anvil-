"""Phase 1 — strategy/signal layer. All deterministic on the demo connector (no keys).

Asserts: every candidate is finite-risk + carries the decision policy; regime gating routes
premium-selling to a positive-gamma chain; edge_prob is a valid market-implied probability and
equals the matching distribution prob; sizing respects the risk cap and lot granularity; and the
"no-trade" verdict fires on negative-EV / unsizable structures.
"""

from __future__ import annotations

import math

from anvil.ingest.demo import build_demo_chain
from anvil.strategy import NO_TRADE, TRADE, SignalContext, generate_candidates
from anvil.strategy.sizing import SizingConfig, kelly_fraction_star, size_units


def _ctx(spot: float = 24000.0) -> SignalContext:
    return SignalContext(build_demo_chain("NIFTY", spot=spot))


def test_candidates_are_finite_risk_and_carry_decision_policy():
    cands = generate_candidates(_ctx(), equity=1_000_000.0)
    assert cands, "expected at least some candidates on the demo chain"
    for c in cands:
        # Defined OR naked, max_loss is always finite and positive (never None/NaN/inf).
        assert c.max_loss > 0 and math.isfinite(c.max_loss)
        assert 0.0 <= c.edge_prob <= 1.0
        assert 0.0 <= c.conviction <= 1.0
        assert c.action in (TRADE, NO_TRADE)
        # Decision policy is populated for explainability.
        assert c.entry_reason and c.invalidation_condition
        assert "regime_fit" in c.score_components
        assert c.to_dict()["strategy"] == c.strategy  # json-safe round trips


def test_positive_gamma_chain_routes_to_premium_selling():
    cands = generate_candidates(_ctx(), equity=1_000_000.0)
    traded = [c.strategy for c in cands if c.action == TRADE]
    assert traded, "positive-gamma chain should yield tradeable premium-selling structures"
    # The taken trades are neutral premium structures, not long-vol buys.
    assert any(s in ("iron_condor", "short_strangle", "iv_crush_fade") for s in traded)
    assert "long_straddle" not in traded  # buying vol has negative EV under the VRP


def test_edge_prob_matches_market_implied_distribution():
    ctx = _ctx()
    cands = generate_candidates(ctx, equity=1_000_000.0)
    condor = next((c for c in cands if c.strategy == "iron_condor"), None)
    assert condor is not None
    lo, hi = condor.breakevens
    # Edge for a credit condor is the physical-measure probability of finishing inside the wings.
    expected = ctx.prob_between_physical(lo, hi)
    assert expected is not None
    assert abs(condor.edge_prob - expected) < 1e-9


def test_sizing_respects_risk_fraction_and_lots():
    cfg = SizingConfig(risk_fraction=0.05, kelly_fraction=0.55, max_exposure_pct=0.40, max_lots_per_underlying=20)
    # A 60%-edge bet that pays 1:1, ₹2,000 risk/unit, ₹1,000,000 equity.
    units, info = size_units(2_000.0, 0.60, 2_000.0, 1_000_000.0, cfg)
    assert units >= 1
    # Never exceed the risk-fraction budget: units * risk <= risk_fraction * equity.
    assert units * 2_000.0 <= 0.05 * 1_000_000.0 + 1e-6
    assert units <= cfg.max_lots_per_underlying
    assert info["units"] == units
    # A negative-edge Kelly bet sizes to zero (no-trade).
    z, _ = size_units(2_000.0, 0.40, 1_000.0, 1_000_000.0, cfg)
    assert z == 0


def test_kelly_fraction_star_math():
    # f* = p - (1-p)/b ; p=0.6, b=2 -> 0.6 - 0.4/2 = 0.4
    assert abs(kelly_fraction_star(0.60, 2.0) - 0.40) < 1e-9
    assert kelly_fraction_star(0.40, 0.5) == 0.0  # clamped at zero


def test_no_trade_fires_on_unsizable_or_negative_ev():
    cands = generate_candidates(_ctx(), equity=1_000_000.0)
    nts = [c for c in cands if c.action == NO_TRADE]
    assert nts, "some structures should be rejected (long-vol / illiquid / negative-EV)"
    for c in nts:
        assert c.score_components.get("no_trade_reasons")
