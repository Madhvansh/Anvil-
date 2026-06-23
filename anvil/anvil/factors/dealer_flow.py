"""Dealer-flow factors (Innovation I.1) — surface the vanna/charm hedging stack + gamma-flip level as
display-safe ``FactorSignal``s over ``ctx.dealer_flow``.

These are STRUCTURAL (dealers *must* re-hedge their books) but INDIA-UNVALIDATED for directional use
(the research report warns SPX dealer mechanics may not transfer), so every factor is **CONFIRMATION**
tier and **abstain-safe**: it fires only on a material, near-spot signal, and returns ``fired=False``
(never crashes) when the dealer-flow read is missing — so the legacy path is unperturbed and these only
*corroborate*, never headline alone. Like all factors they are display/metadata only (they populate the
prediction's signals + ``signals_fired``; they do not move conviction/sizing — the gate certifies edge).
"""

from __future__ import annotations

from ..engine.dealer_flow import dealer_hedge_drift, gamma_flip_levels
from ..strategy.types import BEARISH, BULLISH, NEUTRAL
from .base import CONFIRMATION, FactorSignal, register

GAMMA_FLIP_SR = "gamma_flip_sr"
CHARM_PIN = "charm_pin"
VANNA_DRIFT = "vanna_drift"

# Spot must be within this fraction of the flip for it to act as an intraday S/R level.
_FLIP_BAND = 0.005
# Charm pinning is an expiry-week phenomenon; a dominant charm wall this close to spot pins.
_PIN_MAX_DTE = 3.0
_PIN_BAND = 0.01


def _abstain(name: str, reason: str) -> FactorSignal:
    return FactorSignal(name, False, 0.0, "", CONFIRMATION, {"reason": reason})


@register(GAMMA_FLIP_SR)
def gamma_flip_sr(ctx) -> FactorSignal:
    """The zero-gamma flip as an intraday support/resistance band: fires when spot is hugging the flip
    (the regime hinge — above = pinned/mean-reverting, below = trending). Direction-less context."""
    df = getattr(ctx, "dealer_flow", None)
    if df is None or getattr(df, "zero_gamma_flip", None) is None:
        return _abstain(GAMMA_FLIP_SR, "no_flip")
    lvl = gamma_flip_levels(df.zero_gamma_flip, ctx.spot)
    if lvl is None:
        return _abstain(GAMMA_FLIP_SR, "no_level")
    dist = abs(lvl["distance"])
    if dist > _FLIP_BAND:
        return FactorSignal(GAMMA_FLIP_SR, False, 0.0, "", CONFIRMATION,
                            {"distance": lvl["distance"], "regime": lvl["regime"]})
    strength = max(0.0, min(1.0, 1.0 - dist / _FLIP_BAND))
    return FactorSignal(GAMMA_FLIP_SR, True, float(strength), NEUTRAL, CONFIRMATION,
                        {"flip": lvl["flip"], "acts_as": lvl["acts_as"], "regime": lvl["regime"],
                         "distance": lvl["distance"]})


@register(CHARM_PIN)
def charm_pin(ctx) -> FactorSignal:
    """Expiry-week charm pinning: near expiry, a dominant charm wall hugging spot drags the close toward
    that strike (NEUTRAL/pin). Abstains away from expiry or when no charm wall is near spot."""
    df = getattr(ctx, "dealer_flow", None)
    if df is None or not getattr(df, "charm_walls", None) or ctx.spot <= 0:
        return _abstain(CHARM_PIN, "no_charm")
    dte = float(getattr(ctx, "T", 0.0)) * 365.0
    if dte > _PIN_MAX_DTE:
        return FactorSignal(CHARM_PIN, False, 0.0, "", CONFIRMATION, {"dte": round(dte, 2)})
    strike, _expo = df.charm_walls[0]
    dist = abs(float(strike) - ctx.spot) / ctx.spot
    if dist > _PIN_BAND:
        return FactorSignal(CHARM_PIN, False, 0.0, "", CONFIRMATION,
                            {"dte": round(dte, 2), "nearest_charm_strike": strike})
    strength = max(0.0, min(1.0, 1.0 - dist / _PIN_BAND))
    return FactorSignal(CHARM_PIN, True, float(strength), NEUTRAL, CONFIRMATION,
                        {"pin_strike": strike, "dte": round(dte, 2), "distance": dist})


@register(VANNA_DRIFT)
def vanna_drift(ctx) -> FactorSignal:
    """Vanna hedging drift: when IV is moving (``ctx.flow.iv_rank`` velocity) and the dealer book is
    one-sided in vanna, dealers must re-hedge in a predictable direction. Couples the dealer-flow stack
    with flow momentum (orthogonal fusion). CONFIRMATION + india-unvalidated; abstains without both reads."""
    df = getattr(ctx, "dealer_flow", None)
    flow = getattr(ctx, "flow", None)
    if df is None:
        return _abstain(VANNA_DRIFT, "no_dealer_flow")
    ivr = getattr(flow, "iv_rank", None) if flow is not None else None
    chg = ivr.get("change_points") if ivr else None
    if not chg:
        return _abstain(VANNA_DRIFT, "no_iv_velocity")
    drift = dealer_hedge_drift(df, iv_change_pts=float(chg), days=0.0)
    flowdir = drift["rehedge_flow"]
    if flowdir == "sell_underlying":
        direction = BEARISH
    elif flowdir == "buy_underlying":
        direction = BULLISH
    else:
        return FactorSignal(VANNA_DRIFT, False, 0.0, "", CONFIRMATION, {"reason": "neutral_drift"})
    strength = max(0.0, min(0.6, abs(float(chg)) / 10.0))  # bigger IV move → stronger (bounded, modest)
    return FactorSignal(VANNA_DRIFT, True, float(strength), direction, CONFIRMATION,
                        {"iv_change_pts": chg, "rehedge_flow": flowdir,
                         "delta_accumulated": drift["delta_accumulated"], "note": "india_unvalidated"})
