"""Data provenance stamped onto every analytics payload.

Answers, for any number the product shows: where did it come from, when, what forward was
used, and is it live / backtested / demo / derived. This is the trust surface — the UI shows
a provenance chip and an offline "as of" label from it, and it keeps demo data visibly demo.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..models import OptionChain
from .greeks import ENGINE_VERSION

# Data lineage of an analytics payload.
LIVE = "live"
BACKTEST = "backtest"
DEMO = "demo"
DERIVED = "derived"


def data_mode(source: str | None) -> str:
    """Map a connector/source name to a lineage mode. Synthetic sources (demo/seed) are
    flagged demo so they can never be passed off as a live read."""
    if not source:
        return DERIVED
    s = source.lower()
    if s in ("demo", "seed"):
        return DEMO
    if s == "backtest":
        return BACKTEST
    return LIVE


def provenance(chain: OptionChain, *, source: str | None = None, derived_from: str | None = None) -> dict:
    return {
        "source": source or "unknown",
        "mode": data_mode(source),
        "timestamp": chain.timestamp,
        "as_of": chain.timestamp,
        "underlying": chain.underlying,
        "spot": chain.spot,
        "expiry": chain.expiry,
        "forward": chain.future_price,
        "forward_source": chain.future_price_source,
        "vix": chain.vix,
        "engine_version": ENGINE_VERSION,
        "derived_from": derived_from,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
