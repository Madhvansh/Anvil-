"""Phase 1 — the EOD positioning feed: cached, provenance-tagged, honest on failure."""

from __future__ import annotations

from anvil.ingest import positioning
from anvil.ingest.nse_eod import ParticipantOI


def test_fetch_and_cache_is_provenance_tagged(tmp_path, monkeypatch):
    monkeypatch.setattr(positioning, "_cache_dir", lambda: tmp_path)
    rows = [{"Client Type": "FII", "Future Index Long": "100", "Future Index Short": "50"}]
    res = positioning.fetch_and_cache_positioning(
        date_iso="2025-09-01",
        _participant=lambda ddmmyyyy: ParticipantOI(date=ddmmyyyy, rows=rows),
        _vix=lambda: 12.5,
    )
    assert res["participants"] == 1 and res["vix"] == 12.5 and res["error"] is None
    blob = positioning.read_positioning("2025-09-01")
    assert blob["source_class"] == "nse_eod" and blob["india_vix"] == 12.5
    assert blob["participants"][0]["Client Type"] == "FII"
    assert positioning.available_dates() == ["2025-09-01"]


def test_total_failure_writes_no_hollow_file(tmp_path, monkeypatch):
    monkeypatch.setattr(positioning, "_cache_dir", lambda: tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("blocked by anti-bot")

    res = positioning.fetch_and_cache_positioning(
        date_iso="2025-09-02", _participant=boom, _vix=lambda: None)
    assert res["path"] is None and res["error"] and res["participants"] == 0
    assert positioning.read_positioning("2025-09-02") is None  # gap surfaced, no fabricated file
