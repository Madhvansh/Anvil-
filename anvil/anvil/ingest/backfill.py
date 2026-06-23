"""Hardened multi-month NSE F&O bhavcopy backfill — resume, retry/backoff, polite rate-limit.

``bhavcopy.fetch_bhavcopy_text`` fetches one day; the CLI's old loop was a naive serial pull that NSE's
anti-bot layer kills after ~50 requests, leaving an unresumable partial cache. A ~500-request 24-month
pull needs four things, which this adds without touching the fetcher:

  * **resume** — skip dates already cached (so a killed run continues where it stopped);
  * **retry with exponential backoff + jitter** on transient failures (429/503/timeout/anti-bot);
  * **polite rate-limit** — a minimum delay per request + bounded concurrency;
  * **trading-day awareness** — weekends/holidays are skipped via the trading calendar, not fetched.

Fail-soft per day with an **honest summary**: a day that genuinely won't fetch is *reported in the
missing list*, never silently papered over (NSE archives move; a gap is information).
"""

from __future__ import annotations

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from ..live.trading_calendar import trading_days
from .bhavcopy import RateLimited, fetch_bhavcopy_text


def cache_path(cache_dir: Path, d: date) -> Path:
    return Path(cache_dir) / f"fo_{d.isoformat()}.csv"


def _is_cached(cache_dir: Path, d: date) -> bool:
    p = cache_path(cache_dir, d)
    return p.exists() and p.stat().st_size > 0


def fetch_one(
    d: date, cache_dir: Path, *, max_retries: int = 4, base_delay: float = 1.5, timeout: float = 20.0,
    sleep=time.sleep, fetch=fetch_bhavcopy_text, rng: random.Random | None = None,
) -> tuple[str, str]:
    """Fetch+cache one day with exponential backoff. Returns ``(status, detail)`` where status is
    ``cached`` (already on disk), ``fetched`` (newly written), or ``failed`` (gave up)."""
    path = cache_path(cache_dir, d)
    if _is_cached(cache_dir, d):
        return ("cached", str(path))
    rng = rng or random
    last = "no attempt"
    for attempt in range(max(1, max_retries)):
        try:
            text = fetch(d, timeout=timeout)
            path.write_text(text, encoding="utf-8")
            return ("fetched", str(path))
        except RateLimited as e:  # honor the server's pace: back off ≥ Retry-After before retrying
            last = str(e)[:160]
            if attempt < max_retries - 1:
                backoff = max(float(e.retry_after), base_delay * (2 ** attempt))
                sleep(backoff + rng.uniform(0.0, base_delay))
        except Exception as e:  # noqa: BLE001 - NSE is fragile; backoff and retry
            last = str(e)[:160]
            if attempt < max_retries - 1:
                sleep(base_delay * (2 ** attempt) + rng.uniform(0.0, base_delay))
    return ("failed", last)


def backfill_bhavcopy(
    start: date, end: date, cache_dir, *, workers: int = 3, min_delay: float = 0.4,
    max_retries: int = 4, sleep=time.sleep, fetch=fetch_bhavcopy_text, progress=None, log_path=None,
) -> dict:
    """Backfill every trading day in ``[start, end]`` into ``cache_dir``. Resumes (skips cached),
    retries with backoff (honoring 429/503 Retry-After), bounded concurrency + a polite ``min_delay``
    per request. When ``log_path`` is set, appends one checkpoint line per completed day (status + running
    tally) so a multi-hour run is observable and obviously resumable. Returns a summary including the
    **missing-day list** (days that genuinely could not be fetched)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    days = trading_days(start, end)
    todo = [d for d in days if not _is_cached(cache_dir, d)]
    already = len(days) - len(todo)
    fetched: list[str] = []
    failed: list[str] = []
    done = 0
    total = len(todo)
    log_fh = open(log_path, "a", encoding="utf-8") if log_path else None
    if log_fh:
        log_fh.write(f"# backfill {start.isoformat()}..{end.isoformat()} todo={total} "
                     f"cached={already} workers={workers}\n")
        log_fh.flush()

    def _job(d: date) -> tuple[date, str, str]:
        status, detail = fetch_one(d, cache_dir, max_retries=max_retries, sleep=sleep, fetch=fetch)
        if min_delay:
            sleep(min_delay)  # throttle each worker (politeness, not correctness)
        return d, status, detail

    def _record(d: date, status: str, detail: str) -> None:
        nonlocal done
        done += 1
        if status == "fetched":
            fetched.append(d.isoformat())
        elif status == "failed":
            failed.append(d.isoformat())
        if log_fh:  # checkpoint: a long run is observable + obviously resume-safe (cached are skipped)
            log_fh.write(f"{d.isoformat()}\t{status}\t{done}/{total}\tfetched={len(fetched)}\t"
                         f"failed={len(failed)}\t{detail[:80]}\n")
            log_fh.flush()
        if progress:
            progress(d, status, detail)

    try:
        if max(1, workers) == 1:
            for d in todo:
                _record(*_job(d))
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(_job, d): d for d in todo}
                for fut in as_completed(futs):
                    _record(*fut.result())
    finally:
        if log_fh:
            log_fh.write(f"# done fetched={len(fetched)} failed={len(failed)}\n")
            log_fh.close()

    return {
        "trading_days": len(days),
        "already_cached": already,
        "fetched": len(fetched),
        "failed": sorted(failed),
        "missing": sorted(failed),
        "cache_dir": str(cache_dir),
    }
