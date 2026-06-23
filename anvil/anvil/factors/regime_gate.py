"""Regime gate — the single biggest empirical lift is NOT trading in the wrong regime.

Classify the current tape into a small bucket from the existing regime read + IV rank + event/crush
state, then mask factors whose direction doesn't belong in that bucket. Masked factors don't count
toward a tip's signals_fired/conviction. The bucket is recorded into the ledger ``params`` so the
gate's own contribution is measurable (per-regime win-rate).
"""

from __future__ import annotations

from ..strategy.types import BEARISH, BULLISH, LONG_VOL, SHORT_VOL
from .base import FactorSignal

PIN_LOW_VOL = "pin_low_vol"
TREND_HIGH_VOL = "trend_high_vol"
EVENT_CRUSH = "event_crush"
NEUTRAL_REGIME = "neutral"

# Directions that are structurally wrong in each regime and get masked.
_MASKED_DIRECTIONS: dict[str, set[str]] = {
    TREND_HIGH_VOL: {SHORT_VOL},                # don't sell premium into a trend-amplifying tape
    PIN_LOW_VOL: {LONG_VOL},                     # don't buy vol in a pinned/low-vol tape
    EVENT_CRUSH: {LONG_VOL, BULLISH, BEARISH},   # premium dynamics dominate direction near events
}


def classify_regime(ctx) -> str:
    """Bucket the tape: event_crush (scheduled-event/expiry/IV-crush) takes precedence, then the
    dealer-gamma regime, else neutral."""
    crush = ctx.crush or {}
    ev = ctx.event or {}
    score = crush.get("crush_score", 0) or 0
    days = ev.get("days_to_expiry")
    if score >= 66 or (days is not None and days <= 1.0) or ev.get("risk_level") == "high":
        return EVENT_CRUSH
    label = getattr(ctx.regime, "label", "")
    if label == "positive_gamma_mean_revert":
        return PIN_LOW_VOL
    if label == "negative_gamma_trend_amplify":
        return TREND_HIGH_VOL
    return NEUTRAL_REGIME


def apply_regime_mask(signals: list[FactorSignal], bucket: str) -> list[FactorSignal]:
    """Set ``regime_mask=False`` on any signal whose direction is wrong for ``bucket``. Mutates and
    returns the same list (so .active reflects the gate)."""
    masked = _MASKED_DIRECTIONS.get(bucket, set())
    for s in signals:
        if s.direction and s.direction in masked:
            s.regime_mask = False
    return signals
