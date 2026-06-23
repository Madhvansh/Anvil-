"""Phase 1 — hardened bhavcopy backfill: resume, retry/backoff, honest missing-day reporting."""

from __future__ import annotations

from datetime import date

from anvil.ingest.backfill import backfill_bhavcopy, fetch_one

_NOSLEEP = lambda *_a, **_k: None  # noqa: E731


def test_resume_skips_already_cached(tmp_path):
    (tmp_path / "fo_2025-09-01.csv").write_text("cached", encoding="utf-8")  # Monday, already on disk
    fetched = []

    def fetch(d, timeout=20.0):
        fetched.append(d.isoformat())
        return "INSTRUMENT,SYMBOL\n"

    res = backfill_bhavcopy(date(2025, 9, 1), date(2025, 9, 2), tmp_path, workers=1,
                            sleep=_NOSLEEP, fetch=fetch)
    assert res["already_cached"] == 1
    assert fetched == ["2025-09-02"]  # only the uncached trading day was fetched (resume)
    assert res["fetched"] == 1 and res["missing"] == []


def test_retry_then_success(tmp_path):
    attempts = {"n": 0}

    def flaky(d, timeout=20.0):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("429 too many requests")
        return "INSTRUMENT,SYMBOL\n"

    status, _ = fetch_one(date(2025, 9, 2), tmp_path, sleep=_NOSLEEP, fetch=flaky)
    assert status == "fetched" and attempts["n"] == 3  # backed off twice, then succeeded


def test_permanent_failure_is_reported_not_hidden(tmp_path):
    def boom(d, timeout=20.0):
        raise RuntimeError("blocked by anti-bot")

    res = backfill_bhavcopy(date(2025, 9, 2), date(2025, 9, 2), tmp_path, workers=1,
                            sleep=_NOSLEEP, fetch=boom, max_retries=2)
    assert res["missing"] == ["2025-09-02"] and res["fetched"] == 0  # gap surfaced, not papered over


def test_weekends_and_holidays_are_not_fetched(tmp_path):
    seen = []

    def fetch(d, timeout=20.0):
        seen.append(d.isoformat())
        return "INSTRUMENT,SYMBOL\n"

    # 2025-08-14 Thu, 08-15 Independence Day (holiday), 08-16/17 weekend, 08-18 Mon
    res = backfill_bhavcopy(date(2025, 8, 14), date(2025, 8, 18), tmp_path, workers=1,
                            sleep=_NOSLEEP, fetch=fetch)
    assert set(seen) == {"2025-08-14", "2025-08-18"} and res["trading_days"] == 2
