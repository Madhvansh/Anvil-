"""Phase 1 — data-health report: coverage, honest gap reporting, source reconciliation."""

from __future__ import annotations

import json

from anvil.backtest.health import data_health_report


def _write_bhav(cache_dir, dates):
    for d in dates:
        (cache_dir / f"fo_{d}.csv").write_text("INSTRUMENT,SYMBOL\n", encoding="utf-8")


def test_reports_missing_trading_days_but_excludes_holidays(tmp_path):
    # Mon..Fri of a week, but DROP Wed 2025-09-03 → a real gap; no holiday in the span.
    _write_bhav(tmp_path, ["2025-09-01", "2025-09-02", "2025-09-04", "2025-09-05"])
    rep = data_health_report(cache_dir=str(tmp_path))
    assert rep["bhavcopy"]["days"] == 4
    assert rep["bhavcopy"]["missing_trading_days"] == ["2025-09-03"]  # the dropped Wednesday
    assert rep["ok"] is True  # gaps are informational, not a failure


def test_reconciliation_flags_a_real_mismatch(tmp_path, monkeypatch):
    import anvil.backtest.health as health

    _write_bhav(tmp_path, ["2025-09-01", "2025-09-02"])
    (tmp_path / "index_close.json").write_text(json.dumps({
        "2025-09-01": {"NIFTY": 24600.0},   # agrees with yahoo (below)
        "2025-09-02": {"NIFTY": 30000.0},   # way off → integrity FAILURE
    }), encoding="utf-8")
    # Stub the Yahoo cache read so the test is hermetic.
    monkeypatch.setattr(health.yahoo, "read_cache", lambda sym: (
        [{"date": "2025-09-01", "o": 0, "h": 0, "l": 0, "c": 24605.0, "volume": 0},
         {"date": "2025-09-02", "o": 0, "h": 0, "l": 0, "c": 24650.0, "volume": 0}]
        if sym == "^NSEI" else []))
    rep = data_health_report(cache_dir=str(tmp_path))
    assert rep["reconciliation"]["checked"] == 2
    assert len(rep["reconciliation"]["failures"]) == 1
    assert rep["reconciliation"]["failures"][0]["date"] == "2025-09-02"
    assert rep["ok"] is False  # a >1.5% disagreement on a settle is an integrity failure
