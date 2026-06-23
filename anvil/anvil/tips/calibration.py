"""Tip calibration bridge — feed issued tips and their outcomes into the DuckDB moat.

On ISSUE we record a ``trade_win`` forecast with ``prob = conviction`` under the tip source class
(``tip_live`` for forward/live, ``tip_backtest`` for out-of-sample history); on resolution we record
the win/loss. The ledger's scoring then answers the only question that matters: "when a tip said
65%, did ~65% win, after costs?". These classes are NOT in PUBLIC_CLASSES, so issued-tip reliability
lives on its own curve (``metrics_for_tips``) and never blends into the market-implied probability
calibration or the owner-only paper/today curves.
"""

from __future__ import annotations

from ..ledger.ledger import KIND_TRADE_WIN, CalibrationLedger, Forecast
from .types import Tip


def record_tip(ledger: CalibrationLedger, tip: Tip, spot: float, forward: float) -> str:
    """Record an issued tip's conviction forecast. Sets ``tip.ledger_forecast_id`` and returns it.
    Idempotent: re-recording the same tip is a no-op (deterministic forecast id)."""
    f = Forecast(
        underlying=tip.underlying,
        created_ts=tip.created_ts,
        resolve_ts=tip.resolve_ts,
        kind=KIND_TRADE_WIN,
        params={
            "tip_id": tip.tip_id,
            "structure": tip.structure,
            "direction": tip.direction,
            "tier": tip.tier,
            "signals": tip.signals_fired,
            "regime_bucket": tip.regime_bucket,
            "horizon_days": tip.horizon_days,
            "target": tip.target,
            "stop": tip.stop,
        },
        prob=float(tip.conviction),
        spot=float(spot),
        forward=float(forward),
        model_version=tip.model_version,
        source=tip.source,
    )
    fid = ledger.record(f)
    tip.ledger_forecast_id = fid
    return fid


def resolve_tip(
    ledger: CalibrationLedger, tip: Tip, outcome: int | bool, resolved_ts: str | None = None
) -> int | None:
    """Resolve a recorded tip. ``outcome`` is the win/loss event (1/True = win). Returns the event,
    or None if the tip was never recorded. KIND_TRADE_WIN resolves on realized_value > 0, so we pass
    +1.0 for a win and -1.0 for a loss."""
    if not tip.ledger_forecast_id:
        return None
    realized = 1.0 if int(outcome) else -1.0
    return ledger.resolve(tip.ledger_forecast_id, realized, resolved_ts=resolved_ts)


def tip_calibration(ledger: CalibrationLedger, n_bins: int = 10) -> dict:
    """The public issued-tip reliability curves (tip_backtest + tip_live)."""
    return ledger.metrics_for_tips(n_bins=n_bins)
