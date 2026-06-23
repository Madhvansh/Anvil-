"""NSE/NSDL end-of-day datasets: participant-wise OI, FII/DII flows, India VIX.

These India-specific datasets have NO official real-time API — they're published as
free CSV/JSON at ~5:30-6:30 PM IST. NSE endpoints are undocumented and anti-bot
(require a browser-like session: cookies + referer + UA), so this is a *best-effort*
scraper with a clear caveat. In production, prefer a maintained library
(nsepython / jugaad-data) or a licensed aggregator, and schedule this nightly.

Nothing here is needed for the offline demo; it's the V1 flow-data layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import httpx

_NSE_HOME = "https://www.nseindia.com"
_PARTICIPANT_OI = "https://archives.nseindia.com/content/nsccl/fao_participant_oi_{ddmmyyyy}.csv"

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _NSE_HOME,
}


@dataclass
class ParticipantOI:
    date: str
    rows: list[dict] = field(default_factory=list)  # client/dii/fii/pro x future/option longs/shorts


def _session() -> httpx.Client:
    """An NSE session that first hits the homepage to acquire anti-bot cookies."""
    c = httpx.Client(timeout=15.0, headers=_BROWSER_HEADERS, follow_redirects=True)
    try:
        c.get(_NSE_HOME)  # warm cookies
    except httpx.HTTPError:
        pass
    return c


def fetch_participant_oi(ddmmyyyy: str) -> ParticipantOI:
    """Participant-wise OI (FII/DII/Pro/Client) for a given date (DDMMYYYY).

    Raises on network failure — callers should treat NSE scraping as fragile and have
    an aggregator fallback.
    """
    url = _PARTICIPANT_OI.format(ddmmyyyy=ddmmyyyy)
    with _session() as c:
        r = c.get(url)
        r.raise_for_status()
        text = r.text
    lines = [ln for ln in text.splitlines() if ln.strip()]
    # File has a title row, then a header, then client/DII/FII/Pro/TOTAL rows.
    rows: list[dict] = []
    header = None
    for ln in lines:
        cells = [c.strip() for c in ln.split(",")]
        if cells and cells[0].lower() in ("client", "dii", "fii", "pro", "total"):
            if header:
                rows.append(dict(zip(header, cells)))
        elif "Client Type" in ln or "Future Index Long" in ln:
            header = cells
    return ParticipantOI(date=ddmmyyyy, rows=rows)


def fetch_india_vix() -> float | None:
    """Live India VIX level via NSE index quote (best-effort)."""
    with _session() as c:
        try:
            r = c.get(f"{_NSE_HOME}/api/allIndices")
            r.raise_for_status()
            for idx in r.json().get("data", []):
                if idx.get("index", "").upper().startswith("INDIA VIX"):
                    return float(idx.get("last"))
        except (httpx.HTTPError, ValueError, KeyError):
            return None
    return None
