"""Phase 5 — the live trust dial (tips/trust_dial.build_trust_dial): composes reliability +
accuracy-at-coverage + coverage + the tail-stats scorecard + per-cell verdicts + VRP-prior + gate
status. Display-only; reads the same vstore the gate writes."""

from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.store import IssuedTipStore, TipValidationStore
from anvil.tips.trust_dial import _tail_metrics, build_trust_dial


def test_tail_metrics_mandatory_block():
    m = _tail_metrics([100.0, -50.0, 200.0, -30.0, -300.0])
    assert m["n"] == 5
    # win-rate never alone — the tail block is always present
    for k in ("max_drawdown_inr", "worst_trade_inr", "cvar_5pct_inr", "sharpe", "sortino"):
        assert k in m
    assert m["worst_trade_inr"] == -300.0
    assert m["max_drawdown_inr"] <= 0


def test_tail_metrics_empty():
    assert _tail_metrics([]) == {"n": 0}


def test_build_trust_dial_composes(tmp_path):
    led = CalibrationLedger(str(tmp_path / "l.duckdb"))
    vstore = TipValidationStore(str(tmp_path / "tv.duckdb"))
    istore = IssuedTipStore(str(tmp_path / "iss.duckdb"))
    try:
        dial = build_trust_dial(led=led, istore=istore, vstore=vstore,
                                vrp_prior={"label": "real_vrp_prior", "metrics": {}})
        for k in ("reliability", "accuracy_at_coverage", "coverage", "scorecard", "cells",
                  "vrp_prior", "gate", "disclaimer"):
            assert k in dial
        assert dial["gate"]["armed"] in (True, False)
        assert dial["gate"]["gate0_passed"] is False  # empty vstore → no certified cell
        assert dial["accuracy_at_coverage"]["status"].startswith("no certified")
        assert dial["vrp_prior"]["note"] == "prior, NOT a track record"
        assert dial["scorecard"]["resolved"] == 0
    finally:
        led.close()
        vstore.close()
        istore.close()
