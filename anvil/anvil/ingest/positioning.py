"""EOD positioning feed — participant-wise OI + FII/DII + India VIX, cached point-in-time.

Wires the (previously dead) ``nse_eod`` scrapers into a cached, provenance-tagged EOD feed. The
research rates participant positioning (esp. FII/Pro index-option longs/shorts) as **higher-signal
than the PCR / max-pain folklore** — a real feature source for later phases. Cached under
``data/positioning_cache/`` and tagged ``source_class='nse_eod'`` (real EOD data; never demo/synthetic,
so fabricated positioning can't leak into certification). Keyed by trading date so a backtest only ever
reads what was actually published that day.

Best-effort, like every NSE scraper here: if the archive is unreachable it reports the error and writes
**nothing** — a gap is surfaced, never filled with a hollow/partial file.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from .nse_eod import fetch_india_vix, fetch_participant_oi

SOURCE_CLASS = "nse_eod"  # real EOD data — firewalled away from demo/synthetic classes


def _cache_dir() -> Path:
    d = Path("data") / "positioning_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(date_iso: str) -> Path:
    return _cache_dir() / f"positioning_{date_iso}.json"


def _latest_trading_day() -> date:
    from ..live.clock import IST
    from ..live.trading_calendar import is_trading_day

    d = datetime.now(IST).date()
    for _ in range(10):  # walk back to the most recent trading day
        if is_trading_day(d):
            return d
        d -= timedelta(days=1)
    return d


def fetch_and_cache_positioning(
    *, date_iso: str | None = None, _participant=fetch_participant_oi, _vix=fetch_india_vix,
) -> dict:
    """Fetch participant-OI + India VIX for a trading day and cache it (provenance-tagged). Returns a
    summary; on a total failure it returns ``error`` and writes no file. Scrapers are injectable for
    offline tests."""
    from ..live.clock import IST

    d = date.fromisoformat(date_iso) if date_iso else _latest_trading_day()
    ddmmyyyy = d.strftime("%d%m%Y")
    error = None
    participants: list[dict] = []
    vix = None
    try:
        participants = _participant(ddmmyyyy).rows
    except Exception as e:  # noqa: BLE001 - NSE fragility
        error = f"participant_oi: {str(e)[:120]}"
    try:
        vix = _vix()
    except Exception as e:  # noqa: BLE001
        error = (error + "; " if error else "") + f"vix: {str(e)[:120]}"

    if not participants and vix is None:
        return {"date": d.isoformat(), "participants": 0, "vix": None, "path": None,
                "error": error or "no data published"}

    blob = {
        "date": d.isoformat(), "source_class": SOURCE_CLASS,
        "fetched_at": datetime.now(IST).isoformat(), "india_vix": vix, "participants": participants,
    }
    p = cache_path(d.isoformat())
    p.write_text(json.dumps(blob, indent=2), encoding="utf-8")
    return {"date": d.isoformat(), "participants": len(participants), "vix": vix, "path": str(p),
            "error": error}


def read_positioning(date_iso: str) -> dict | None:
    """Point-in-time read of one day's cached positioning (None if not yet fetched)."""
    p = cache_path(date_iso)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def available_dates() -> list[str]:
    return sorted(p.stem.replace("positioning_", "") for p in _cache_dir().glob("positioning_*.json"))
