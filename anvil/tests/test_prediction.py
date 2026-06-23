"""The always-on prediction layer: a ``Prediction`` is ALWAYS produced (so the live feed is never
empty) — even on a chain with no validation evidence — and ``edge_verified`` flips False→True ONLY
when the validation store holds a ``headline_eligible`` cell for the prediction's
``(structure, regime_bucket, underlying)``. Confidence stays a calibratable number, never asserted."""

from __future__ import annotations

from anvil.ingest.base import attach_parity_forward
from anvil.ingest.demo import build_demo_chain
from anvil.strategy.types import BEARISH, BULLISH, LONG_VOL, NEUTRAL, SHORT_VOL
from anvil.tips.predict import predict_for_chain
from anvil.tips.store import TipValidationReport, TipValidationStore

_DIRECTIONS = {BULLISH, BEARISH, NEUTRAL, LONG_VOL, SHORT_VOL}


def _chain():
    return attach_parity_forward(
        build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31",
                         timestamp="2026-06-20T15:30:00+05:30"))


def test_prediction_always_present_without_store():
    _ctx, _bucket, _signals, pred, _tips = predict_for_chain(
        _chain(), source="demo", equity=1_000_000.0, validation_store=None)
    d = pred.to_dict()
    assert d["underlying"] == "NIFTY"
    assert d["direction"] in _DIRECTIONS
    assert 0.0 <= d["confidence"] <= 1.0
    assert d["confidence_basis"]
    assert d["edge_verified"] is False  # no store ⇒ never verified
    assert d["disclaimer"]
    assert isinstance(d["factors"], list) and len(d["factors"]) > 0
    assert d["summary"]


def test_with_risk_flag_controls_owner_overlay():
    # The owner risk overlay is expensive (mc_pnl + ruin MC) and owner-only, so it is computed ONLY
    # when the caller asks (``with_risk``) — the public surface strips it anyway. Default: skipped.
    ch = _chain()
    _c, _b, _s, pred_no, _t = predict_for_chain(
        ch, source="demo", equity=1_000_000.0, validation_store=None, with_risk=False)
    assert pred_no.risk_distribution is None and pred_no.roe_overlay is None and pred_no.risk_of_ruin is None
    _c2, _b2, _s2, pred_yes, _t2 = predict_for_chain(
        ch, source="demo", equity=1_000_000.0, validation_store=None, with_risk=True)
    if pred_yes.has_actionable_tip:  # when a tradeable tip exists, the (cheap) ROE overlay computes
        assert pred_yes.roe_overlay is not None


def test_edge_verified_flips_with_seeded_cell(tmp_path):
    store = TipValidationStore(str(tmp_path / "tv.duckdb"))
    try:
        # 1) Discover the prediction's leading structure + regime bucket with an EMPTY store.
        _ctx, bucket, _signals, pred, _tips = predict_for_chain(
            _chain(), source="demo", equity=1_000_000.0, validation_store=store)
        assert pred.edge_verified is False
        structure = pred.best_structure
        assert structure

        # 2) Seed a headline_eligible cell for exactly that (structure, bucket, underlying).
        store.upsert(TipValidationReport(
            structure=structure, regime_bucket=bucket, underlying="NIFTY", n=80,
            win_rate=0.66, mean_conviction=0.60, mean_net_pnl=1234.0, cost_adjusted_edge=0.05,
            t_stat=3.5, dsr=0.97, pbo=0.20, robustness_p_low=0.01, headline_eligible=True,
            updated_ts="2026-06-20"))

        # 3) Re-run: the ✓ badge is now earned (read from the SAME store the gate reads).
        _c, _b, _s, pred2, _t = predict_for_chain(
            _chain(), source="demo", equity=1_000_000.0, validation_store=store)
        assert pred2.edge_verified is True
        assert pred2.edge_verified_basis and pred2.edge_verified_basis["n"] == 80
    finally:
        store.close()
