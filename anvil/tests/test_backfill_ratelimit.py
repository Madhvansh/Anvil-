"""Phase 3 — backfill hardening for the long 24-month pull: honor 429/503 Retry-After, resume cached,
checkpoint log. (Legacy pre-2024 schema parsing is covered by ``test_bhavcopy_legacy``.)"""

from __future__ import annotations

import random
from datetime import date

from anvil.ingest.backfill import backfill_bhavcopy, cache_path, fetch_one
from anvil.ingest.bhavcopy import RateLimited, _retry_after_seconds


class _Resp:
    def __init__(self, headers):
        self.headers = headers


def test_retry_after_parsing():
    assert _retry_after_seconds(_Resp({"Retry-After": "12"})) == 12.0
    assert _retry_after_seconds(_Resp({"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})) == 0.0
    assert _retry_after_seconds(_Resp({})) == 0.0


def test_fetch_one_resumes_cached(tmp_path):
    d = date(2026, 6, 2)
    cache_path(tmp_path, d).write_text("already", encoding="utf-8")
    calls = []

    def fake(dd, timeout=20.0):
        calls.append(dd)
        return "x"

    status, _ = fetch_one(d, tmp_path, fetch=fake, sleep=lambda s: None)
    assert status == "cached"
    assert calls == []  # resume: a cached day is never re-fetched (so a killed run continues)


def test_fetch_one_honors_retry_after_backoff(tmp_path):
    d = date(2026, 6, 3)
    slept: list[float] = []
    attempts = {"n": 0}

    def fake(dd, timeout=20.0):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RateLimited(7.0)  # NSE throttles twice, then yields
        return "csvdata"

    status, detail = fetch_one(d, tmp_path, fetch=fake, sleep=lambda s: slept.append(s),
                               base_delay=1.0, rng=random.Random(0))
    assert status == "fetched" and attempts["n"] == 3
    assert any(s >= 7.0 for s in slept), "must back off at least the server's Retry-After seconds"
    assert cache_path(tmp_path, d).read_text(encoding="utf-8") == "csvdata"


def test_backfill_skips_cached_and_reports_missing(tmp_path):
    cache_path(tmp_path, date(2026, 6, 1)).write_text("pre", encoding="utf-8")  # already cached

    def fake(dd, timeout=20.0):
        if dd == date(2026, 6, 3):
            raise RuntimeError("holiday/layout miss")
        return "csv"

    res = backfill_bhavcopy(date(2026, 6, 1), date(2026, 6, 3), tmp_path, workers=1,
                            fetch=fake, sleep=lambda s: None, min_delay=0,
                            log_path=str(tmp_path / "backfill.log"))
    assert res["trading_days"] == 3
    assert res["already_cached"] == 1            # 2026-06-01 skipped (resume)
    assert res["fetched"] == 1                   # 2026-06-02 fetched
    assert res["missing"] == ["2026-06-03"]      # honest miss list, not hidden
    log = open(tmp_path / "backfill.log", encoding="utf-8").read()
    assert "2026-06-02\tfetched" in log and "# done" in log  # checkpoint log written + closed
