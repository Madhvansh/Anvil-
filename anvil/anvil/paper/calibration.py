"""Conviction calibration bridge — feed paper-trade outcomes into the DuckDB moat.

On OPEN we record a ``trade_win`` forecast with ``prob = conviction`` under the EXCLUDED ``paper``
source class; on CLOSE we resolve it from realized P&L (win = P&L > 0). The existing
``ledger/scoring.py`` then answers the only question that matters for "does our edge work?":
when we said 60%, did ~60% of those trades actually win? COMPLIANCE: the ``paper`` class is not in
``PUBLIC_CLASSES``, so these never touch the public market-implied reliability curves.
"""

from __future__ import annotations

from ..ledger.ledger import KIND_TRADE_WIN, CalibrationLedger, Forecast
from .state import PaperPosition

PAPER_SOURCE = "paper"


def record_conviction(ledger: CalibrationLedger, pos: PaperPosition, spot: float, forward: float) -> str:
    """Record a conviction forecast for an opened paper position. Returns the forecast id."""
    f = Forecast(
        underlying=pos.underlying,
        created_ts=pos.opened_at,
        resolve_ts=pos.legs[0].expiry if pos.legs else pos.opened_at,
        kind=KIND_TRADE_WIN,
        params={"position_id": pos.id, "strategy": pos.strategy, "direction": pos.direction},
        prob=float(pos.conviction),
        spot=float(spot),
        forward=float(forward),
        source=PAPER_SOURCE,
    )
    fid = ledger.record(f)
    pos.ledger_forecast_id = fid
    return fid


def resolve_conviction(ledger: CalibrationLedger, pos: PaperPosition) -> int | None:
    """Resolve a closed position's conviction forecast from realized P&L (win = P&L > 0)."""
    if not pos.ledger_forecast_id:
        return None
    return ledger.resolve(pos.ledger_forecast_id, float(pos.realized_pnl), resolved_ts=pos.closed_at)


def paper_calibration(ledger: CalibrationLedger, n_bins: int = 10) -> dict:
    """Owner-only conviction reliability for paper trades (the EXCLUDED ``paper`` class)."""
    return ledger.metrics(n_bins=n_bins, classes=(PAPER_SOURCE,))
