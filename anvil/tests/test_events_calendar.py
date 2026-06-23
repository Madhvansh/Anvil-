"""Phase 1 — events/earnings calendar: macro events load from CSV; per-stock earnings stay separate."""

from __future__ import annotations

from anvil.ingest import events


def test_macro_calendar_loaded_from_committed_csv():
    cal = dict(events.calendar())
    assert cal.get("2025-02-01") == "Union Budget"
    assert "RBI MPC" in cal.values()
    assert all(d != "date" for d, _ in events.calendar())  # header row not ingested as an event


def test_days_to_next_event_finds_upcoming_macro():
    nxt = events.days_to_next_event("2025-09-15")
    assert nxt and nxt["name"] == "RBI MPC" and nxt["date"] == "2025-10-01" and nxt["days"] == 16


def test_earnings_are_separate_per_stock_and_dont_pollute_macro():
    macro_names = {n for _, n in events.calendar()}
    assert "TCS" not in macro_names and "RELIANCE" not in macro_names  # earnings ≠ macro events
    e = events.days_to_next_earnings("INFY", "2025-10-01")
    assert e and e["symbol"] == "INFY" and e["date"] == "2025-10-16"
    # a symbol with no earnings on/after the date → None
    assert events.days_to_next_earnings("INFY", "2027-01-01") is None
