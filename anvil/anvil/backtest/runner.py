"""Walk-forward backtest: for each historical trading day, record forward-looking forecasts
from that day's chains and resolve any forecast whose expiry settles that day — producing a
real, out-of-sample reliability curve in the ledger under ``source='backtest'``.

Determinism/idempotency: forecast ids are content-hashed and inserts are ON CONFLICT DO
NOTHING, so re-running a date range reproduces identical metrics (a tested guarantee).
"""

from __future__ import annotations

from datetime import date

from ..engine.implied_dist import implied_distribution
from ..ledger.ledger import CalibrationLedger, emit_forecasts
from .asof import AsOfContext
from .data import BhavcopyArchive


def run_backtest(
    archive: BhavcopyArchive,
    underlyings: list[str] | tuple[str, ...],
    ledger: CalibrationLedger,
    *,
    start: date | None = None,
    end: date | None = None,
    source: str = "backtest",
) -> dict:
    underlyings = [u.upper() for u in underlyings]
    recorded = 0
    resolved = 0
    for d in archive.trading_days(start, end):
        ctx = AsOfContext(d, archive)
        today = d.isoformat()

        # 1) Record forward-looking forecasts from each open, liquid chain (look-ahead guarded).
        for u in underlyings:
            for ch in ctx.open_chains(u):
                dist = implied_distribution(ch)
                if dist is None:
                    continue
                recorded += ledger.record_many(emit_forecasts(ch, dist, source=source))

        # 2) Resolve forecasts whose expiry settles exactly today, at TODAY's realized close
        #    (read on the expiry date — never earlier, never a stand-in "now").
        for u in underlyings:
            level = ctx.realized_level(u)
            if level is None:
                continue
            for p in ledger.pending(u):
                if p["resolve_ts"] == today:
                    ledger.resolve(p["id"], realized_value=level, resolved_ts=f"{today}T16:00:00+05:30")
                    resolved += 1

    return {
        "recorded": recorded,
        "resolved": resolved,
        "metrics": ledger.metrics(classes=("backtest",)),
    }
