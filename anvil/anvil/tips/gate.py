"""The headline / watchlist gate — pure, reads MEASURED evidence only.

A tip is promoted to HEADLINE iff (1) its (structure, regime_bucket, underlying) cell has a stored
validation report flagged ``headline_eligible`` (the backtest's conjunction of sample-size +
calibrated win-rate + positive post-cost edge + Harvey t-stat + Deflated Sharpe + low PBO + robust
bootstrap), AND (2) the tip's own cost-adjusted EV is positive. Everything else tradeable stays on
the WATCHLIST. The gate never asserts edge it hasn't measured — so an empty headline feed is the
correct, honest default until evidence accrues.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import SETTINGS
from .store import GATE_VERSION
from .types import HEADLINE, WATCHLIST, Tip

_IST = timezone(timedelta(hours=5, minutes=30))


def _is_stale(updated_ts, now: datetime, max_stale_days: int) -> bool:
    """True iff ``updated_ts`` parses and is older than ``max_stale_days``. Empty/unparseable → not
    stale (the check is skipped), so legacy/seeded reports with ``updated_ts=''`` are unaffected."""
    if not updated_ts:
        return False
    try:
        ts = datetime.fromisoformat(str(updated_ts))
    except (ValueError, TypeError):
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=_IST)
    return (now - ts).days > max_stale_days


def decide_tier(tip: Tip, store, *, model_version: str = GATE_VERSION,
                max_stale_days: int | None = None, now: datetime | None = None) -> str:
    """Return HEADLINE or WATCHLIST for ``tip`` given the validation ``store`` (or None).

    A green verdict is honoured only if it was certified by the CURRENT gate AND is fresh: a report
    stamped with a different ``model_version`` (the gate's inputs/logic moved on under it), or whose
    ``updated_ts`` is older than ``max_stale_days`` (default ``SETTINGS.gate_max_stale_days``), is
    demoted to the watchlist rather than trusted. Verdicts with no version stamp or an empty/unparseable
    ``updated_ts`` skip that respective check (so legacy/hand-seeded rows keep working)."""
    if store is None:
        return WATCHLIST
    if tip.cost_adjusted_ev is None or tip.cost_adjusted_ev <= 0:
        return WATCHLIST  # a tip that doesn't clear its own costs can never headline
    report = store.get(tip.structure, tip.regime_bucket, tip.underlying)
    if not (report and report.get("headline_eligible")):
        return WATCHLIST
    stamped = report.get("model_version")
    if stamped and stamped != model_version:
        return WATCHLIST  # certified by a superseded gate → stale, don't trust the ✓
    max_stale_days = SETTINGS.gate_max_stale_days if max_stale_days is None else max_stale_days
    if _is_stale(report.get("updated_ts"), now or datetime.now(_IST), max_stale_days):
        return WATCHLIST  # verdict too old → re-certify before trusting it
    return HEADLINE


def apply_tier(tip: Tip, store, *, model_version: str = GATE_VERSION,
               max_stale_days: int | None = None, now: datetime | None = None) -> Tip:
    """Set ``tip.tier`` from the gate and return the tip (mutates in place)."""
    tip.tier = decide_tier(tip, store, model_version=model_version,
                           max_stale_days=max_stale_days, now=now)
    return tip
