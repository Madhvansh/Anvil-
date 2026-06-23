"""Calibration ledger — the trust engine and moat.

Every probabilistic forecast Anvil makes is logged with a timestamp and later scored
against the realized outcome. The public reliability curve ("when we say 70%, it happens
~70% of the time") is what lets the product market accuracy honestly and is the asset a
competitor cannot back-fill. See docs/decisions/0004-calibration-first-compliance.md.
"""

from .ledger import CalibrationLedger, Forecast, emit_forecasts, event_for
from .scoring import brier_score, coverage, log_loss, reliability_curve

__all__ = [
    "CalibrationLedger",
    "Forecast",
    "emit_forecasts",
    "event_for",
    "brier_score",
    "log_loss",
    "reliability_curve",
    "coverage",
]
