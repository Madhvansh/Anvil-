"""Realized-close resolution source — the "what level did it settle at?" question, answered causally.

A strict source ladder so resolution is honest and never guessed:
  1. ``BhavcopyArchive`` (official cash close / front-future proxy / equity close) — point-in-time,
     used only when a prebuilt archive is supplied (building one per cycle parses 100s of CSVs, so
     it is opt-in via ``archive``; the daily moat clock uses Yahoo for the cheap recent close).
  2. Yahoo daily cache (``^NSEI``/``^NSEBANK``/``^BSESN``/``{SYM}.NS``) — matched on the exact ``day``.
  3. Connector spot — last resort, ONLY when ``day`` is today AND the market is closed (flagged proxy).

A day that hasn't settled yet yields NOTHING for that underlying (causal — never resolve early); a
missing underlying is OMITTED, never guessed. VIX is never a resolution level (it only feeds the VRP
prior). ``realized_closes_for`` returns ``{U: close}``; ``realized_closes_with_sources`` adds the
``{U: source}`` rung for the trust-dial honesty line.
"""

from __future__ import annotations

from datetime import date, datetime

from ..ingest import yahoo
from .clock import IST, is_market_open


def _from_archive(archive, u: str, d: date) -> float | None:
    try:
        v = archive.index_close_on(d, u)
        if v is None:
            v = archive.equity_close_on(d, u)
        return float(v) if v is not None else None
    except Exception:  # noqa: BLE001 - a bad archive must never sink resolution
        return None


def _from_yahoo(u: str, day: str) -> float | None:
    sym = yahoo.INDEX_SYMBOL.get(u.upper(), f"{u.upper()}.NS")
    if sym.upper() == "^INDIAVIX":  # never settle an option against the VIX level
        return None
    for b in yahoo.read_cache(sym):
        if str(b.get("date", ""))[:10] == day[:10]:
            try:
                return float(b["c"])
            except (TypeError, ValueError, KeyError):
                return None
    return None


def _market_closed_today(day: str) -> bool:
    try:
        now = datetime.now(IST)
        return day[:10] == now.date().isoformat() and not is_market_open(now)
    except Exception:  # noqa: BLE001
        return False


def realized_closes_with_sources(
    underlyings,
    day: str,
    *,
    connector=None,
    archive=None,
    allow_spot_fallback: bool = True,
) -> dict[str, tuple[float, str]]:
    """``{U: (close, source)}`` for each underlying that can be priced CAUSALLY for ``day``.

    Underlyings that can't be priced (not yet settled, no cache) are omitted, never guessed. The spot
    fallback fires only after the cash close on the same day, and never for VIX."""
    conn = connector
    spot_ok = allow_spot_fallback and _market_closed_today(day)
    if spot_ok and conn is None:
        try:
            from ..ingest import get_connector

            conn = get_connector()
        except Exception:  # noqa: BLE001
            conn = None
    out: dict[str, tuple[float, str]] = {}
    for u in underlyings:
        uu = str(u).upper()
        if uu == "INDIAVIX":
            continue
        close: float | None = None
        source = ""
        if archive is not None:
            try:
                close = _from_archive(archive, uu, date.fromisoformat(day[:10]))
                source = "bhavcopy"
            except ValueError:
                close = None
        if close is None:
            close = _from_yahoo(uu, day)
            source = "yahoo" if close is not None else source
        if close is None and spot_ok and conn is not None:
            try:
                spot = float(conn.get_chain(uu).spot)
                if spot > 0:
                    close, source = spot, "spot_proxy"
            except Exception:  # noqa: BLE001
                close = None
        if close is not None:
            out[uu] = (close, source)
    return out


def realized_closes_for(
    underlyings,
    day: str,
    *,
    connector=None,
    archive=None,
    allow_spot_fallback: bool = True,
) -> dict[str, float]:
    """``{U: close}`` resolution levels per priced underlying (missing ones omitted, never guessed)."""
    return {
        u: c
        for u, (c, _s) in realized_closes_with_sources(
            underlyings, day, connector=connector, archive=archive,
            allow_spot_fallback=allow_spot_fallback,
        ).items()
    }
