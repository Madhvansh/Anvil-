"""Daily live forecast + resolve loop — the moat clock.

Run once each trading day after the cash close (e.g. via Windows Task Scheduler). It:
  1. pulls the live chain for each underlying and logs probabilistic forecasts (the band/
     direction set from the implied distribution), tagged with the real connector source;
  2. resolves any forecast whose expiry has now passed, against the realized index close.

Idempotent by construction: forecast ids are content-hashed and inserts are ON CONFLICT DO
NOTHING, so re-running a day cannot inflate the track record. Resolution levels are supplied
explicitly (the official close), never guessed from an intraday tick.
"""

from __future__ import annotations

from ..engine.implied_dist import implied_distribution
from ..ingest import get_connector
from ..ledger.ledger import CalibrationLedger, emit_forecasts


def run_daily(
    underlyings: list[str] | tuple[str, ...] = ("NIFTY",),
    *,
    connector=None,
    ledger: CalibrationLedger | None = None,
    realized: dict[str, float] | None = None,
    as_of: str | None = None,
    source: str | None = None,
    auto_resolve: bool = False,
) -> dict:
    """Record today's forecasts and resolve any now-due ones.

    ``connector`` defaults to the configured live source; ``source`` defaults to the connector
    name (demo data lands in the excluded 'demo' class, real data in 'live'). ``realized`` maps
    underlying → the official close to resolve due forecasts against.
    """
    owns_ledger = ledger is None
    led = ledger or CalibrationLedger()
    conn = connector or get_connector()
    src = source or conn.name  # demo→excluded; upstox/groww/…→live (see source_class)
    try:
        recorded: dict[str, int] = {}
        cycle_day = ""
        for u in underlyings:
            ch = conn.get_chain(u)
            # Anchor the forecast to the trading day's close (not the wall-clock run time) so a
            # same-day re-run is idempotent — the deterministic id then dedups exactly.
            day = (ch.timestamp or "")[:10]
            if day:
                ch = ch.model_copy(update={"timestamp": f"{day}T15:30:00+05:30"})
                cycle_day = day
            dist = implied_distribution(ch)
            recorded[u] = led.record_many(emit_forecasts(ch, dist, source=src)) if dist else 0

        # Auto-resolution (Phase 5): fetch the published close so due forecasts resolve themselves.
        rday = (as_of or cycle_day or "")[:10]
        if realized is None and auto_resolve and rday:
            from .closes import realized_closes_for

            realized = realized_closes_for(
                [u.upper() for u in underlyings], rday, connector=conn, allow_spot_fallback=False)

        resolved: dict[str, int] = {}
        for u, level in (realized or {}).items():
            resolved[u.upper()] = led.resolve_due(u.upper(), float(level), as_of)

        return {"recorded": recorded, "resolved": resolved, "source": src}
    finally:
        if owns_ledger:
            led.close()
