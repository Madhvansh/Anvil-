"""Anvil tips layer — the PUBLIC, edge-scored projection of the (private) strategy candidate engine.

A ``Tip`` is a deterministic, structured, edge-scored trade idea (instrument/structure, direction,
entry/target/stop, horizon, calibrated conviction, the signals that fired, and cost-adjusted EV).
Tips are recorded into the calibration ledger under the ``tip_backtest``/``tip_live`` source classes
and scored exactly like any forecast — so the headline feed can be gated on MEASURED, post-cost,
out-of-sample edge rather than asserted accuracy.

This package is the only sanctioned public consumer of ``anvil.strategy`` (read-only). It does NOT
import ``anvil.paper`` (tips are predictions, not simulated fills), keeping the paper subsystem
private behind its own feature flag.
"""

from .build import round_trip_cost, tip_from_candidate
from .calibration import record_tip, resolve_tip, tip_calibration
from .resolve import resolve_outcome_from_path, resolve_outcome_from_pnl, terminal_payoff
from .types import TIP_DISCLAIMER, Tip

__all__ = [
    "Tip",
    "TIP_DISCLAIMER",
    "tip_from_candidate",
    "round_trip_cost",
    "record_tip",
    "resolve_tip",
    "tip_calibration",
    "resolve_outcome_from_path",
    "resolve_outcome_from_pnl",
    "terminal_payoff",
]
