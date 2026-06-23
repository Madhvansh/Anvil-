"""Yahoo chart JSON parsing (pandas-free) with the C6 IST date discipline: a UTC-boundary timestamp
maps to the correct IST trading date, null/gap bars are skipped (not interpolated), and weekend bars
are dropped."""

from __future__ import annotations

import datetime as dt
import json

from anvil.ingest.yahoo import ohlc_tuples, parse_chart_json


def _payload(timestamps, o, h, low, c, v=None):
    return json.dumps({"chart": {"result": [{
        "timestamp": timestamps,
        "indicators": {"quote": [{"open": o, "high": h, "low": low, "close": c,
                                  "volume": v or [1] * len(o)}]}}], "error": None}})


def test_utc_boundary_maps_to_ist_date():
    # 2026-06-21 is a Sunday; 19:00 UTC + 5:30 = 2026-06-22 00:30 IST (Monday) → date 2026-06-22.
    epoch = int(dt.datetime(2026, 6, 21, 19, 0, tzinfo=dt.timezone.utc).timestamp())
    res = parse_chart_json(_payload([epoch], [100.0], [101.0], [99.0], [100.5]))
    assert len(res["bars"]) == 1 and res["bars"][0]["date"] == "2026-06-22"


def test_null_gap_is_skipped_not_interpolated():
    # A real NSE bar ~03:45 UTC (09:15 IST) on a weekday; one bar has a null close → skipped.
    e1 = int(dt.datetime(2026, 6, 22, 3, 45, tzinfo=dt.timezone.utc).timestamp())  # Mon
    e2 = int(dt.datetime(2026, 6, 23, 3, 45, tzinfo=dt.timezone.utc).timestamp())  # Tue
    res = parse_chart_json(_payload([e1, e2], [100.0, 101.0], [102.0, 103.0], [99.0, 100.0],
                                    [101.0, None]))
    assert res["skipped"] == 1 and len(res["bars"]) == 1 and res["bars"][0]["date"] == "2026-06-22"


def test_weekend_bar_dropped_and_tuples():
    sat = int(dt.datetime(2026, 6, 20, 6, 0, tzinfo=dt.timezone.utc).timestamp())  # Saturday IST
    mon = int(dt.datetime(2026, 6, 22, 3, 45, tzinfo=dt.timezone.utc).timestamp())
    res = parse_chart_json(_payload([sat, mon], [100.0, 101.0], [102.0, 103.0], [99.0, 100.0],
                                    [101.0, 102.0]))
    assert [b["date"] for b in res["bars"]] == ["2026-06-22"]
    assert ohlc_tuples(res["bars"]) == [(101.0, 103.0, 100.0, 102.0)]
