"""Phase 4 — run report, Performance Lab, and conviction calibration feedback. The compliance
rail (paper outcomes excluded from the public moat) is a first-class assertion here."""

from __future__ import annotations

from anvil.ledger.ledger import CalibrationLedger
from anvil.live.realtime import RealtimeEngine

START = "2026-06-19T03:45:00+00:00"
EXPIRY = "2026-06-26"


def test_report_shape_and_perf_lab(tmp_path):
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    rep = RealtimeEngine(ledger=led).replay(["NIFTY"], start_ts=START, expiry=EXPIRY, steps=6, cadence_s=14400, seed=7)
    for key in ("summary", "trades", "risk", "attribution", "performance_lab", "equity_curve", "conviction_calibration"):
        assert key in rep
    s = rep["summary"]
    assert abs(s["ending_equity"] - (s["starting_capital"] + s["net_pnl"])) < 1.0
    pl = rep["performance_lab"]
    assert pl["n"] == rep["trades"]["n_total"]
    for row in pl["trades"]:
        assert "mae" in row and "mfe" in row and "slippage_cost" in row and "won" in row
    led.close()


def test_conviction_recorded_and_resolved(tmp_path):
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    RealtimeEngine(ledger=led).replay(["NIFTY"], start_ts=START, expiry=EXPIRY, steps=6, cadence_s=14400, seed=7)
    paper = led.metrics(classes=("paper",))
    # Every opened+closed paper trade resolves a conviction forecast.
    assert paper["resolved_count"] >= 1
    assert paper["pending_count"] == 0
    led.close()


def test_paper_calibration_excluded_from_public_moat(tmp_path):
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    RealtimeEngine(ledger=led).replay(["NIFTY"], start_ts=START, expiry=EXPIRY, steps=6, cadence_s=14400, seed=7)
    public = led.metrics()  # default = PUBLIC_CLASSES (backtest + live)
    by_class = led.metrics_by_class()
    # The whole compliance rail: paper trades NEVER enter the public reliability curves.
    assert public["resolved_count"] == 0
    assert "paper" not in by_class
    assert led.metrics(classes=("paper",))["resolved_count"] >= 1
    led.close()
