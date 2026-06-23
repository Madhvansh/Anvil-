"""Phase 5 — portfolio short-vol stress cap (paper/governor.cap_short_vol_exposure, ported from v2).
Short-vol legs across indices gap together, so the TOTAL stress max-loss is capped; the marginal
candidate is downsized to fit and the rest dropped. Non-short-vol candidates are untouched."""

from anvil.paper.governor import cap_short_vol_exposure
from anvil.strategy.types import NEUTRAL, NO_TRADE, TRADE, TradeCandidate


def _cand(underlying, max_loss, *, units=1, regime_kind="short_vol", rank=1.0):
    c = TradeCandidate(
        strategy="short_strangle", underlying=underlying, direction=NEUTRAL, legs=[], lot_size=1,
        edge_prob=0.6, conviction=0.6, entry_debit_credit=0.0, max_loss=max_loss, max_profit=1000.0,
        breakevens=[], expected_value=rank * max_loss, horizon_days=5.0)
    c.units, c.regime_kind, c.action = units, regime_kind, TRADE
    return c


def test_cap_drops_lowest_ranked_over_cap():
    c1 = _cand("NIFTY", 300000.0, rank=2.0)       # higher rank → kept
    c2 = _cand("BANKNIFTY", 300000.0, rank=1.0)   # lower rank → over cap, can't fit → dropped
    cap_short_vol_exposure([c1, c2], equity=1_000_000.0, max_exposure_pct=0.40)  # cap = 400k
    assert c1.action == TRADE and c1.units == 1
    assert c2.action == NO_TRADE and c2.units == 0
    assert "portfolio_short_vol_cap" in c2.score_components["no_trade_reasons"]


def test_cap_downsizes_marginal():
    c1 = _cand("NIFTY", 300000.0, units=1, rank=2.0)
    c2 = _cand("BANKNIFTY", 500000.0, units=10, rank=1.0)  # per-unit 50k; room 100k → fit 2
    cap_short_vol_exposure([c1, c2], equity=1_000_000.0, max_exposure_pct=0.40)
    assert c2.units == 2
    assert "downsized_by_portfolio_cap" in c2.score_components["no_trade_reasons"]


def test_non_short_vol_untouched():
    c = _cand("NIFTY", 900000.0, regime_kind="long_vol", rank=1.0)
    cap_short_vol_exposure([c], equity=1_000_000.0, max_exposure_pct=0.40)
    assert c.action == TRADE and c.units == 1
