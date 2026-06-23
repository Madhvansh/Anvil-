"""Scheduled-event calendar — the dates where premium dynamics dominate direction (RBI policy, the
Union Budget, big macro prints). Used by the ``scheduled_event`` factor to abstain from / fade into
known events, which the plan calls a STRONG gate ("abstaining buys accuracy").

Seed dates are committed (no network), and an optional ``data/events.csv`` (``date,name`` rows)
overrides/extends them — so single-stock earnings or fresh RBI dates drop in without code changes.
Dates are India calendar dates (IST); only the date matters for the days-to-event gate.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

# Committed seed: RBI MPC decision days + the Union Budget. Extend via data/events.csv.
_SEED: list[tuple[str, str]] = [
    ("2025-10-01", "RBI MPC"),
    ("2025-12-05", "RBI MPC"),
    ("2026-02-01", "Union Budget"),
    ("2026-02-06", "RBI MPC"),
    ("2026-04-08", "RBI MPC"),
    ("2026-06-05", "RBI MPC"),
    ("2026-08-05", "RBI MPC"),
]


def _data_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def _read_pairs(path: Path) -> list[tuple[str, str]]:
    """Read a 2-column ``a,b`` CSV, skipping ``#`` comments and a ``date`` header row."""
    if not path.exists():
        return []
    out: list[tuple[str, str]] = []
    try:
        for row in csv.reader(path.read_text(encoding="utf-8").splitlines()):
            a = row[0].strip() if row else ""
            if len(row) >= 2 and a and not a.startswith("#") and a.lower() != "date":
                out.append((a, row[1].strip()))
    except OSError:
        pass
    return out


def _load_overrides() -> list[tuple[str, str]]:
    return _read_pairs(_data_dir() / "events.csv")


def calendar() -> list[tuple[str, str]]:
    """Sorted, de-duplicated (date, name) event list (seed + optional CSV overrides)."""
    merged = {d: n for d, n in _SEED}
    for d, n in _load_overrides():
        merged[d] = n
    return sorted(merged.items())


def days_to_next_event(on_iso: str) -> dict | None:
    """The next scheduled event on/after ``on_iso`` (YYYY-MM-DD…): {name, date, days} or None."""
    if not on_iso:
        return None
    try:
        today = date.fromisoformat(on_iso[:10])
    except ValueError:
        return None
    for d_iso, name in calendar():
        try:
            d = date.fromisoformat(d_iso)
        except ValueError:
            continue
        if d >= today:
            return {"name": name, "date": d_iso, "days": (d - today).days}
    return None


def earnings_calendar() -> list[tuple[str, str]]:
    """Sorted ``(date, SYMBOL)`` single-stock earnings from ``data/earnings.csv`` (empty if absent).

    Kept SEPARATE from the index macro ``calendar()`` so a stock's results window never leaks into the
    index event gate. Consumed (point-in-time) by the equity IV-crush gate in a later phase."""
    return sorted((d, s.upper()) for d, s in _read_pairs(_data_dir() / "earnings.csv"))


def days_to_next_earnings(symbol: str, on_iso: str) -> dict | None:
    """Next earnings for ``symbol`` on/after ``on_iso``: ``{symbol, date, days}`` or None."""
    if not on_iso:
        return None
    try:
        today = date.fromisoformat(on_iso[:10])
    except ValueError:
        return None
    sym = symbol.upper()
    for d_iso, s in earnings_calendar():
        if s != sym:
            continue
        try:
            d = date.fromisoformat(d_iso)
        except ValueError:
            continue
        if d >= today:
            return {"symbol": sym, "date": d_iso, "days": (d - today).days}
    return None
