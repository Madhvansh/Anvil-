"""Phase 3 — Gate-0: the EV/accuracy-at-coverage kill switch, in-loop trial-counted thresholds, report.

Covers:
  * ``ev_coverage_threshold`` — OOF EV/coverage, EV-max tau, and that its sweep is COUNTED as trials;
  * the honest mechanism — the in-loop threshold sweep raises the Deflated-Sharpe bar and rejects a cell
    that passed when the search wasn't counted;
  * ``run_gate0`` end-to-end on a synthetic resolved-tip store + the markdown/JSON/SVG artifact.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import numpy as np

from anvil.backtest.aggregate import new_cell, validate_cells
from anvil.backtest.gate0 import run_gate0
from anvil.backtest.gate_report import render_markdown, render_svg, write_gate0_report
from anvil.backtest.trials import TrialRegistry
from anvil.calibration.conformal import ev_coverage_threshold, risk_coverage_threshold
from anvil.calibration.service import CalibrationService
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.store import IssuedTipStore


def test_ev_coverage_threshold_is_oof_and_trial_counted(tmp_path):
    rng = np.random.default_rng(3)
    n = 300
    score = rng.uniform(0.0, 1.0, n)
    # high scores carry positive net-of-cost return; low scores are negative-EV → abstain region
    rets = np.where(score > 0.7, 0.4, -0.1) + rng.normal(0.0, 0.05, n)
    reg = TrialRegistry(path=str(tmp_path / "trials.duckdb"))
    try:
        assert reg.total("ev:test") == 0
        out = ev_coverage_threshold(score, rets, embargo=1, n_splits=5, trial_registry=reg,
                                    trial_scope="ev:test")
        assert reg.total("ev:test") == 46           # the whole tau grid was tried → counted as trials
        assert out["ev"] is not None and out["ev"] > 0
        assert 0.0 < out["coverage"] <= 1.0
        assert 0.5 <= out["tau"] <= 0.95
    finally:
        reg.close()


def _interleave(n, win_rate, win_mag, loss_mag, phase=0.0):
    out, acc = [], float(phase)
    for _ in range(n):
        acc += win_rate
        out.append(win_mag if acc >= 1.0 else -loss_mag)
        if acc >= 1.0:
            acc -= 1.0
    return out


def _day_cell(returns):
    c = new_cell()
    for i, r in enumerate(returns):
        d = f"d{i:03d}"
        c["returns"].append(r)
        c["net"].append(r * 100.0)
        c["conv"].append(0.5)
        c["wins"] += int(r > 0)
        c["by_day"][d].append(r)
    return c


def test_in_loop_threshold_sweep_raises_bar_and_rejects_overfit(tmp_path):
    """Two cells that ARE headline-eligible when the search is uncounted (n_trials=1) must be REJECTED
    once the in-loop threshold sweep's trials are counted into the Deflated Sharpe — the Phase-0 promise,
    now driven by the Gate-0 threshold sweep."""
    cells = {
        ("short_strangle", "pin", "NIFTY"): _day_cell(_interleave(80, 0.72, 0.05, 0.04, 0.0)),
        ("iron_condor", "pin", "NIFTY"): _day_cell(_interleave(80, 0.70, 0.05, 0.04, 0.3)),
    }
    res_days = sorted({d for c in cells.values() for d in c["by_day"]})
    before, _ = validate_cells(cells, res_days, min_samples=2, n_trials=1)
    assert all(r.headline_eligible for r in before), "should pass when the search isn't counted"

    # Simulate the Gate-0 in-loop sweep: each threshold frontier bumps the registry.
    reg = TrialRegistry(path=str(tmp_path / "t.duckdb"))
    try:
        scores = np.linspace(0.5, 0.95, 80)
        events = (np.array(_interleave(80, 0.72, 1, 0, 0.0)) > 0).astype(float)
        rets = np.array(_interleave(80, 0.72, 0.05, 0.04, 0.0))
        risk_coverage_threshold(scores, events, embargo=1, trial_registry=reg, trial_scope="gate0:x")
        ev_coverage_threshold(scores, rets, embargo=1, trial_registry=reg, trial_scope="gate0:x")
        counted = reg.total("gate0:x")
        assert counted >= 92                                   # 46 + 46 grid points
        after, _ = validate_cells(cells, res_days, min_samples=2, n_trials=counted)
        assert all(not r.headline_eligible for r in after), "counting the sweep must reject them"
        assert after[0].dsr < before[0].dsr                    # the bar provably rose
    finally:
        reg.close()


def _weekdays(start: date, n: int) -> list[date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def _seed_resolved_options(istore, n=80, source="tip_backtest"):
    """Insert ``n`` resolved OPTION tips whose win/return rises with conviction (a real, learnable edge),
    spread across distinct resolution days so the day-blocked battery has independent act-days."""
    rng = np.random.default_rng(11)
    days = _weekdays(date(2026, 3, 2), n)
    for i in range(n):
        conv = float(round(0.50 + 0.45 * rng.uniform(), 4))
        win = 1 if rng.uniform() < conv else 0
        ret = 0.4 if win else -0.2
        resolve = f"{days[i].isoformat()}T16:00:00+05:30"
        created = f"{_weekdays(days[i] - timedelta(days=7), 1)[0].isoformat()}T09:30:00+05:30"
        istore.con.execute(
            "INSERT INTO tips_issued (tip_id, ledger_forecast_id, underlying, created_ts, resolve_ts, "
            "structure, regime_bucket, tier, source, lot_size, round_trip_cost, max_loss, legs, payload, "
            "resolved, outcome, resolved_ts, net_pnl, ret) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [f"opt{i}", f"f{i}", "NIFTY", created, resolve, "short_strangle", "pin", "HEADLINE", source,
             50, 10.0, 100.0, json.dumps([]), json.dumps({"conviction": conv}), True, win,
             resolve, ret * 100.0, ret],
        )


def test_run_gate0_end_to_end_and_report(tmp_path):
    istore = IssuedTipStore(path=str(tmp_path / "s.duckdb"))
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    reg = TrialRegistry(path=str(tmp_path / "tr.duckdb"))
    svc = CalibrationService([])  # identity — exercises the uncalibrated/honest path
    try:
        _seed_resolved_options(istore, n=80)
        result = run_gate0(
            issued_store=istore, ledger=led, calibrators=svc,
            sources={"trade": ("tip_backtest",), "struct": ("struct_backtest",)},
            accuracy_target=0.65, min_coverage=0.10, min_samples=5, trial_registry=reg,
            now_ts="2026-06-22T00:00:00Z", date_range=("2026-03-02", "2026-06-19"), depth_days=80,
            provisional=True)

        # structure
        conv = next(t for t in result["targets"] if t["target"] == "conviction")
        assert conv["evaluable"] is True
        assert conv["n"] == 80
        assert "coverage" in conv and "accuracy" in conv and "realized_ev" in conv
        assert conv["curve"]["coverage"] and conv["curve"]["accuracy"]
        assert "realized_ev" in conv["curve"]                 # EV-at-coverage emitted alongside accuracy
        assert conv["trials"] and conv["trials"] > 0          # thresholds counted as trials
        assert conv["calibrated"] is False                    # identity service → flagged honestly
        assert "verdict" in conv and isinstance(conv["verdict"]["pass"], bool)
        assert isinstance(result["verdict"]["pass"], bool)

        # artifact
        paths = write_gate0_report(result, tmp_path / "rep", now_ts="2026-06-22T00:00:00Z")
        js = json.loads(open(paths["json"], encoding="utf-8").read())
        assert js["verdict"]["summary"]
        md = open(paths["markdown"], encoding="utf-8").read()
        assert "PROVISIONAL" in md and "Gate-0" in md and "conviction/tip_backtest" in md
        svg = open(paths["svg"], encoding="utf-8").read()
        assert svg.startswith("<svg") and "coverage" in svg
    finally:
        istore.close()
        led.close()
        reg.close()


def test_report_renders_without_evaluable_targets():
    # An all-abstain result must still render a clean artifact (the honest default on thin data).
    result = {"generated_ts": "t", "gate_version": "g", "calibration_version": "c",
              "thresholds": {"accuracy_target": 0.65, "min_coverage": 0.10},
              "data": {"provisional": True, "depth_days": 62, "date_range": ["a", "b"]},
              "targets": [{"target": "touch", "source_class": "struct_backtest", "n": 4,
                           "evaluable": False, "note": "insufficient evidence",
                           "verdict": {"pass": False, "reasons": ["insufficient evidence"]}}],
              "verdict": {"pass": False, "passing_targets": [], "summary": "ABSTAIN"}}
    assert render_svg(result).startswith("<svg")
    assert "ABSTAIN" in render_markdown(result)
