"""Margin / buying-power model — SPAN-lite (a documented approximation).

For defined-risk structures the realistic broker requirement is the spread's worst case, so we
reserve ``max_loss`` (which also covers any debit paid). For undefined-risk (naked short options,
futures) we approximate SPAN+exposure as a percentage of notional plus premium for short options.

This is NOT a real SPAN engine. The production path is the live broker margin-calculator API
(Upstox ``/charges/margin``, Kite basket-margin, Groww margin) — wired in Phase 3b; this is the
offline/replay fallback and the v1 default.
"""

from __future__ import annotations

SPAN_PCT_FUTURE = 0.12  # ~ index futures SPAN+exposure as a fraction of notional
SPAN_PCT_OPTION = 0.10  # ~ naked short option SPAN component on notional (plus premium)


def required_margin(candidate, spot: float | None = None) -> float:
    """Margin to reserve to OPEN this (already-sized) candidate, in rupees."""
    lot = candidate.lot_size or 1
    if candidate.defined_risk:
        # Spreads/condors/long structures: reserve the modeled worst case (covers debit too).
        return float(max(candidate.max_loss, 0.0))

    total = 0.0
    for leg in candidate.legs:
        qty = int(leg.lots) * lot
        if leg.instrument_type.upper() == "FUT":
            total += SPAN_PCT_FUTURE * float(leg.ref_price) * qty
        elif leg.option_type is not None and str(leg.side).upper() == "SELL":
            notional = float(leg.strike or spot or leg.ref_price) * qty
            total += SPAN_PCT_OPTION * notional + float(leg.ref_price) * qty
        # long option legs: premium is a debit (counted in cash), no extra margin
    return float(total)
