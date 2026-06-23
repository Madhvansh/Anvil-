"""Integration (OVERRIDE 4) — calibration is the honesty rail, NOT a tip-firing / gate unlock.

Asserts: (a) an empty/identity store reproduces current behavior byte-identically; (b) the calibrated
probability populates the DISPLAY fields while sizing still runs off the RAW edge and the recorded
conviction stays RAW (so the gate is unchanged); (c) magic-number paths fall back to the prior
constants when uncalibrated. There is deliberately NO "calibration makes a cell certify" test — that
would reintroduce the in-sample circularity Phase 0 removed.
"""

from __future__ import annotations

import numpy as np

import anvil.strategy.generate as gen
from anvil.calibration import CALIBRATION_VERSION
from anvil.calibration.isotonic import IsotonicCalibrator
from anvil.calibration.service import CalibrationService
from anvil.calibration.store import CalibratorRecord
from anvil.engine.decision_brief import _verdict
from anvil.ingest.base import attach_parity_forward
from anvil.ingest.demo import build_demo_chain
from anvil.strategy.context import SignalContext
from anvil.tips.equities import edge_prob_from_score
from anvil.tips.predict import _direction_from_rnd, predict_for_chain


def _ctx():
    chain = attach_parity_forward(
        build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31",
                         timestamp="2026-06-20T15:30:00+05:30"))
    return SignalContext(chain, source="tip_live")


def _shrinking_service():
    """A fitted conviction/tip_live map that shrinks high convictions downward (≠ identity)."""
    cal = IsotonicCalibrator(np.array([0.0, 0.5, 1.0]), np.array([0.0, 0.30, 0.60]))
    rec = CalibratorRecord(target="conviction", source_class="tip_live", kind="isotonic",
                           params=cal.to_params(), n=400, abstain_tau=0.6,
                           model_version=CALIBRATION_VERSION)
    return CalibrationService([rec])


def test_empty_store_is_byte_identical_in_generate():
    ctx = _ctx()
    base = gen.generate_candidates(ctx, 1_000_000.0)
    empty = gen.generate_candidates(ctx, 1_000_000.0, calibration=CalibrationService([]),
                                    cal_source_class="tip_live")
    assert [c.conviction for c in base] == [c.conviction for c in empty]
    assert all(c.calibrated_edge_prob is None for c in empty)


def test_calibrated_display_set_but_conviction_and_sizing_stay_raw(monkeypatch):
    ctx = _ctx()
    svc = _shrinking_service()

    # conviction is unchanged by calibration (raw _conviction → what the gate records/tests)
    base = gen.generate_candidates(ctx, 1_000_000.0)
    cal = gen.generate_candidates(ctx, 1_000_000.0, calibration=svc, cal_source_class="tip_live")
    assert [round(c.conviction, 6) for c in base] == [round(c.conviction, 6) for c in cal]

    # the calibrated DISPLAY field is populated and differs from the raw edge
    populated = [c for c in cal if c.calibrated_edge_prob is not None]
    assert populated, "expected calibrated_edge_prob to be set when a map exists"
    for c in populated:
        assert c.raw_edge_prob is not None
        assert abs(c.calibrated_edge_prob - c.raw_edge_prob) > 1e-9

    # sizing still receives the RAW edge — never the calibrated value (P4 boundary).
    seen_edges = []
    orig = gen.size_units

    def spy(ml, edge, mp, equity, cfg):
        seen_edges.append(float(edge))
        return orig(ml, edge, mp, equity, cfg)

    monkeypatch.setattr(gen, "size_units", spy)
    cal2 = gen.generate_candidates(ctx, 1_000_000.0, calibration=svc, cal_source_class="tip_live")
    raw_edges = {round(c.raw_edge_prob, 6) for c in cal2 if c.raw_edge_prob is not None}
    assert seen_edges, "size_units should have been called"
    assert all(round(e, 6) in raw_edges for e in seen_edges)


def test_prediction_exposes_calibrated_alongside_raw_without_overwriting():
    chain = attach_parity_forward(
        build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31",
                         timestamp="2026-06-20T15:30:00+05:30"))
    svc = _shrinking_service()
    _c, _b, _s, pred_raw, _t = predict_for_chain(chain, source="demo", equity=1_000_000.0)
    _c, _b, _s, pred_cal, _t = predict_for_chain(chain, source="demo", equity=1_000_000.0,
                                                 calibration=svc, cal_source_class="tip_live")
    # the headline confidence is identical (never overwritten); calibrated rides alongside
    assert pred_cal.confidence == pred_raw.confidence
    assert pred_cal.raw_confidence == round(pred_raw.confidence, 4)


def test_empty_store_prediction_byte_identical():
    chain = attach_parity_forward(
        build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31",
                         timestamp="2026-06-20T15:30:00+05:30"))
    _c, _b, _s, p_none, _t = predict_for_chain(chain, source="demo", equity=1_000_000.0)
    _c, _b, _s, p_empty, _t = predict_for_chain(chain, source="demo", equity=1_000_000.0,
                                               calibration=CalibrationService([]))
    assert p_none.confidence == p_empty.confidence
    assert p_empty.calibrated_confidence is None


def test_magic_numbers_fall_back_to_prior_constants():
    # decision-brief verdict thresholds (0.62 / 0.45)
    assert _verdict({}, 0.63) == "UNFAVORABLE"
    assert _verdict({}, 0.40) == "FAVORABLE"
    assert _verdict({}, 0.55) == "NEUTRAL"
    # equities cap (0.62) unchanged when not overridden
    assert edge_prob_from_score(10.0) == 0.62
    # RND directional thresholds (0.54 / 0.46)
    assert _direction_from_rnd(0.60)[0] == "bullish"
    assert _direction_from_rnd(0.40)[0] == "bearish"
    assert _direction_from_rnd(0.50)[0] == "neutral"
