"""Small shared helpers for the engine."""

from __future__ import annotations

import math
from datetime import datetime, timezone


def json_safe(obj):
    """Recursively replace non-finite floats (NaN/±Inf) with None so payloads are valid JSON.

    Starlette serializes with allow_nan=False and 500s on a NaN; market data + IV inversions can
    legitimately yield NaN, so every computed payload is sanitized before it leaves the API."""
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    return obj

# Indian market close is 15:30 IST. Options expire at close, so time-to-expiry is
# measured to that instant. We use calendar-day year fractions (ACT/365) which is
# the convention vendors use for displayed Greeks.
_SECONDS_PER_YEAR = 365.0 * 24 * 3600
IST_OFFSET_SECONDS = 5.5 * 3600
EXPIRY_HOUR_IST = 15.5  # 15:30


def _parse(ts: str) -> datetime:
    s = ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # bare date
        dt = datetime.fromisoformat(s + "T00:00:00")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def year_fraction(expiry: str, now: str | None = None) -> float:
    """ACT/365 year fraction from ``now`` to ``expiry`` (15:30 IST on expiry day).

    Accepts ISO date or datetime strings. Falls back to current UTC if ``now`` is None.
    Always returns a small positive floor to keep pricing finite on expiry day.
    """
    exp = _parse(expiry)
    # If expiry given as a bare date, set it to 15:30 IST.
    if exp.hour == 0 and exp.minute == 0 and exp.second == 0:
        exp = exp.replace(
            hour=10, minute=0
        )  # 15:30 IST == 10:00 UTC
    now_dt = _parse(now) if now else datetime.now(timezone.utc)
    seconds = (exp - now_dt).total_seconds()
    return max(seconds / _SECONDS_PER_YEAR, 1e-6)
