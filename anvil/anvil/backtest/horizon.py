"""Label-horizon → embargo, shared by all three certification engines.

The walk-forward / combinatorial OUT-OF-FOLD edge checks purge an ``embargo`` gap so a multi-day
label can't leak train↔test. The honest embargo is **the label horizon** — for an option/equity tip,
the number of independent trading days between when it is ISSUED and when it RESOLVES. The EQUITY gate
already threads its fixed holding horizon ([tips/equities.py] ``embargo=int(horizon)``); the OPTION and
LIVE gates were defaulting to ``embargo=5`` regardless of expiry, so a weekly/monthly option whose
label spans more than five days could leak. This module computes the horizon once, in independent-
trading-day units, so all three engines apply the SAME rule.

A single ``validate_cells`` call takes ONE global embargo for a mixed bag of cells, so we use a
configurable high quantile of the observed horizons (default: the MAX — strictly leak-safe; a
monthly-horizon label on thin data then fails the OOF check honestly rather than leaking).
"""

from __future__ import annotations

from datetime import date

import numpy as np


def build_day_index(day_isos) -> dict[str, int]:
    """``{YYYY-MM-DD: position}`` over the sorted unique trading days — the index the OOF splits run on."""
    return {d: i for i, d in enumerate(sorted({(s or "")[:10] for s in day_isos if s}))}


def span_in_index(issue_iso: str, resolve_iso: str, day_index: dict[str, int]) -> int:
    """Independent-trading-day distance between issue and resolution, via a prebuilt ``day_index``.
    0 when either endpoint is absent (can't measure → contributes nothing to the embargo)."""
    i = day_index.get((issue_iso or "")[:10])
    j = day_index.get((resolve_iso or "")[:10])
    if i is None or j is None:
        return 0
    return max(0, j - i)


def calendar_day_index(isos) -> dict[str, int]:
    """Day index over the NSE trading calendar spanning the given ISO dates (for engines without an
    archive, e.g. live re-validation). Falls back to an empty index when no usable dates are present."""
    from ..live.trading_calendar import trading_days

    days = sorted({(s or "")[:10] for s in isos if s})
    if not days:
        return {}
    try:
        lo, hi = date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    except ValueError:
        return {}
    return {d.isoformat(): i for i, d in enumerate(trading_days(lo, hi))}


def robust_embargo(spans, *, default: int = 5, quantile: float = 1.0, minimum: int = 1) -> int:
    """Collapse observed label horizons to one embargo. ``quantile=1.0`` (default) = the MAX horizon
    (strictly leak-safe); a lower quantile (e.g. 0.95) trades a touch of leak-safety for coverage when
    a few long-dated labels would otherwise over-purge. ``default`` when nothing measurable."""
    vals = sorted(int(s) for s in spans if s and int(s) > 0)
    if not vals:
        return int(default)
    e = int(np.ceil(float(np.quantile(vals, float(quantile)))))
    return max(int(minimum), e)


def embargo_from_pairs(pairs, day_index: dict[str, int] | None = None, *, default: int = 5,
                       quantile: float = 1.0) -> int:
    """Embargo from ``(issue_iso, resolve_iso)`` pairs. Builds the day index from the NSE calendar when
    one isn't supplied (the live path); pass a prebuilt archive day index for the backtest paths."""
    pairs = list(pairs)
    idx = day_index
    if idx is None:
        idx = calendar_day_index([p for pr in pairs for p in pr])
    spans = (span_in_index(a, b, idx) for a, b in pairs)
    return robust_embargo(spans, default=default, quantile=quantile)
