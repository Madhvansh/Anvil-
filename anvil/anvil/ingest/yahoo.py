"""Pandas-free daily OHLC + India VIX via the Yahoo chart JSON endpoint — the lightweight history the
decision brief needs (realized-vol forecast, regime) AND the daily HIGH/LOW that makes touch
resolution honest. httpx + stdlib json/csv only (the repo is pandas-free).

C6 — date/timezone discipline (touch-resolution correctness):
  * Yahoo timestamps are epoch UTC; we convert to IST (a fixed +5:30 offset; NSE has no DST) and key
    each bar by its **NSE trading DATE**, so a UTC-boundary bar can't be mapped onto the wrong day.
  * Bars with a null O/H/L/C, or that land on a weekend, are **skipped loudly** (counted), never
    interpolated. Only validated bars are cached.

Symbols: ``^NSEI`` (NIFTY), ``^NSEBANK`` (BANKNIFTY), ``^INDIAVIX``, ``{SYM}.NS`` for cash equities.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

IST = timezone(timedelta(hours=5, minutes=30))
_BASE = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
}


def _cache_dir() -> Path:
    d = Path("data") / "closes_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_path(symbol: str) -> Path:
    safe = symbol.replace("^", "_").replace(".", "_").upper()
    return _cache_dir() / f"{safe}.csv"


def parse_chart_json(text: str) -> dict:
    """Parse a Yahoo chart JSON payload → ``{"bars": [...], "skipped": n}``. Each bar is
    ``{date, o, h, l, c, volume}`` keyed by IST trading date (C6). Raises on a malformed payload."""
    data = json.loads(text)
    chart = data.get("chart") or {}
    res = chart.get("result")
    if not res:
        raise ValueError(f"yahoo chart error: {chart.get('error')}")
    r = res[0]
    ts = r.get("timestamp") or []
    quote = ((r.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, low, c = quote.get("open"), quote.get("high"), quote.get("low"), quote.get("close")
    vol = quote.get("volume")
    bars: list[dict] = []
    seen: set[str] = set()
    skipped = 0
    for i, epoch in enumerate(ts):
        vals = (o[i] if o else None, h[i] if h else None, low[i] if low else None, c[i] if c else None)
        if epoch is None or any(x is None for x in vals):
            skipped += 1
            continue
        d = datetime.fromtimestamp(int(epoch), IST).date()
        if d.weekday() >= 5:  # weekend → not an NSE trading day (fail loudly, don't interpolate)
            skipped += 1
            continue
        di = d.isoformat()
        if di in seen:
            continue
        seen.add(di)
        bars.append({"date": di, "o": float(vals[0]), "h": float(vals[1]), "l": float(vals[2]),
                     "c": float(vals[3]), "volume": float(vol[i]) if (vol and vol[i] is not None) else 0.0})
    bars.sort(key=lambda b: b["date"])
    return {"bars": bars, "skipped": skipped}


def fetch_ohlc(symbol: str, *, range_: str = "2y", interval: str = "1d", timeout: float = 20.0) -> dict:
    """Fetch + parse one symbol's daily OHLC. Returns ``{bars, skipped}``; raises on network failure."""
    with httpx.Client(timeout=timeout, headers=_HEADERS, follow_redirects=True) as cli:
        resp = cli.get(_BASE.format(symbol=symbol), params={"range": range_, "interval": interval})
        resp.raise_for_status()
        return parse_chart_json(resp.text)


def write_cache(symbol: str, bars: list[dict]) -> Path:
    p = cache_path(symbol)
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "o", "h", "l", "c", "volume"])
        for b in bars:
            w.writerow([b["date"], b["o"], b["h"], b["l"], b["c"], b["volume"]])
    return p


def read_cache(symbol: str) -> list[dict]:
    p = cache_path(symbol)
    if not p.exists():
        return []
    out: list[dict] = []
    with open(p, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                out.append({"date": row["date"], "o": float(row["o"]), "h": float(row["h"]),
                            "l": float(row["l"]), "c": float(row["c"]), "volume": float(row["volume"])})
            except (ValueError, KeyError):
                continue
    return out


def fetch_and_cache(symbol: str, *, range_: str = "2y") -> dict:
    """Best-effort: fetch + cache; on any failure fall back to the cached bars. Never raises."""
    try:
        res = fetch_ohlc(symbol, range_=range_)
        if res["bars"]:
            write_cache(symbol, res["bars"])
        return res
    except Exception as e:  # noqa: BLE001 - network/anti-bot fragility; degrade to cache
        return {"bars": read_cache(symbol), "skipped": 0, "error": str(e)[:200], "from_cache": True}


def ohlc_tuples(bars: list[dict]) -> list[tuple]:
    """[(o,h,l,c), …] for the realized-vol / regime engines."""
    return [(b["o"], b["h"], b["l"], b["c"]) for b in bars]


# Underlying → Yahoo symbol for the indices we surface. SENSEX (^BSESN) is BSE — recorded live +
# closes-only for now; its EOD F&O bhavcopy ingestor is deferred (see live/calendar regime breaks).
INDEX_SYMBOL = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK", "INDIAVIX": "^INDIAVIX", "SENSEX": "^BSESN"}


def history_for(underlying: str, *, range_: str = "2y") -> list[dict]:
    """OHLC bars for an underlying (index symbol mapped, else ``{SYM}.NS``). Cache-first, then fetch."""
    sym = INDEX_SYMBOL.get(underlying.upper(), f"{underlying.upper()}.NS")
    cached = read_cache(sym)
    if cached:
        return cached
    return fetch_and_cache(sym, range_=range_)["bars"]
