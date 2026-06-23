"""v1 index-options factors. Each reads only the analytics already on the ``SignalContext`` (no new
pricing). Edge tiers reflect the empirical research: dealer-gamma regime, IV richness, and the
event/IV-crush gate are STRONG; raw directional drift and PCR are CONFIRMATION-only.

NOTE on strengths: ``strength`` is a relative conviction WEIGHT in [0,1], not a probability. The
calibrated probability of a tip is its candidate ``conviction``, scored by the ledger.
"""

from __future__ import annotations

from ..strategy.types import BEARISH, BULLISH, LONG_VOL, NEUTRAL, SHORT_VOL
from .base import CONFIRMATION, STRONG, FactorSignal, register

# GEX normalization scale (₹ dealer-delta change per 1% move). Heuristic, documented: the absolute
# magnitude of total GEX is regime-relative, so we squash it for a 0..1 weight only.
_GEX_SCALE = 5.0e6


@register("gex_regime")
def gex_regime(ctx) -> FactorSignal:
    """Dealer-gamma regime: positive-gamma → mean-revert/pin (favors premium selling); negative →
    trend-amplify (favors long vol). Behavioral/volatility signal, NOT a directional price call.
    Research-grade for India (re-validate; do not import SPX levels)."""
    label = getattr(ctx.regime, "label", "neutral_mixed")
    tg = ctx.gex.total_gex if ctx.gex else 0.0
    if label == "positive_gamma_mean_revert":
        direction, fired = SHORT_VOL, True
    elif label == "negative_gamma_trend_amplify":
        direction, fired = LONG_VOL, True
    else:
        direction, fired = "", False
    strength = round(min(1.0, abs(tg) / _GEX_SCALE), 3) if fired else 0.0
    return FactorSignal(
        "gex_regime", fired, strength, direction, STRONG,
        {"regime": label, "total_gex": tg,
         "zero_gamma_flip": (ctx.gex.zero_gamma_flip if ctx.gex else None)},
    )


@register("iv_rank_extreme")
def iv_rank_extreme(ctx) -> FactorSignal:
    """IV richness: rich IV (rank ≥ 70) favors premium selling, cheap IV (≤ 30) favors buying vol."""
    ivr = ctx.iv_rank
    if ivr is None:
        return FactorSignal("iv_rank_extreme", False, 0.0, "", STRONG,
                            {"iv_rank": None, "reason": "no_iv_history"})
    if ivr >= 70:
        direction, fired, strength = SHORT_VOL, True, min(1.0, (ivr - 70.0) / 30.0)
    elif ivr <= 30:
        direction, fired, strength = LONG_VOL, True, min(1.0, (30.0 - ivr) / 30.0)
    else:
        direction, fired, strength = "", False, 0.0
    return FactorSignal("iv_rank_extreme", fired, round(strength, 3), direction, STRONG,
                        {"iv_rank": ivr})


@register("event_iv_crush")
def event_iv_crush(ctx) -> FactorSignal:
    """Scheduled-event / IV-crush gate. Fires SHORT_VOL to fade rich premium when the crush score is
    high; also sets ``abstain`` when adverse directional/long-vol risk runs into an event/expiry —
    consumed downstream to suppress those tips (abstaining buys accuracy)."""
    crush = ctx.crush or {}
    ev = ctx.event or {}
    score = crush.get("crush_score", 0) or 0
    days = ev.get("days_to_expiry")
    risk = ev.get("risk_level")
    fired = score >= 66
    abstain = (risk == "high") or (days is not None and days <= 1.0)
    direction = SHORT_VOL if fired else ""
    strength = round(min(1.0, score / 100.0), 3) if fired else 0.0
    return FactorSignal("event_iv_crush", fired, strength, direction, STRONG,
                        {"crush_score": score, "days_to_expiry": days,
                         "event_risk": risk, "abstain": abstain})


@register("expiry_gamma")
def expiry_gamma(ctx) -> FactorSignal:
    """Expiry-day dealer-gamma momentum (Baltussen, Da, Lammers & Martens, JFE 2021): near expiry,
    short-gamma dealer hedging trades WITH the move and amplifies it (intraday momentum/continuation).
    Fires on/near expiry in a negative-gamma regime, favouring long-vol / momentum over premium
    selling. The one peer-reviewed directional mechanism here — but India-UNVALIDATED (the Jane Street
    order shows expiry index levels can be engineered, not textbook dealer hedging), so it is
    research-grade and must re-validate on Indian data (the tip backtest) before it can headline."""
    ev = ctx.event or {}
    days = ev.get("days_to_expiry")
    label = getattr(ctx.regime, "label", "")
    tg = ctx.gex.total_gex if ctx.gex else 0.0
    near_expiry = days is not None and days <= 1.0
    short_gamma = label == "negative_gamma_trend_amplify" or tg < 0
    fired = bool(near_expiry and short_gamma)
    strength = round(min(1.0, abs(tg) / _GEX_SCALE), 3) if fired else 0.0
    return FactorSignal(
        "expiry_gamma", fired, strength, LONG_VOL if fired else "", STRONG,
        {"days_to_expiry": days, "regime": label, "total_gex": tg,
         "mechanism": "baltussen_expiry_momentum", "india_unvalidated": True},
    )


@register("oi_gex_confluence")
def oi_gex_confluence(ctx) -> FactorSignal:
    """OI / max-pain / gamma confluence → pinning. Fires NEUTRAL (supports range structures) when
    spot sits near max pain inside a positive-gamma regime."""
    mp = ctx.max_pain
    em = ctx.expected_move
    flip = ctx.gex.zero_gamma_flip if ctx.gex else None
    label = getattr(ctx.regime, "label", "")
    near_pain = mp is not None and em and abs(ctx.spot - mp) <= em
    fired = bool(near_pain and label == "positive_gamma_mean_revert")
    strength = round(max(0.0, 1.0 - abs(ctx.spot - mp) / em), 3) if fired else 0.0
    return FactorSignal("oi_gex_confluence", fired, strength, NEUTRAL if fired else "", STRONG,
                        {"max_pain": mp, "zero_gamma_flip": flip, "pcr_oi": ctx.pcr_oi})


@register("directional_drift")
def directional_drift(ctx) -> FactorSignal:
    """Market-implied directional drift from the risk-neutral density (P(close above spot)).
    CONFIRMATION-only: short-horizon directional edge is weak, so this never headlines alone."""
    pa = ctx.prob_above(ctx.spot)
    if pa is None:
        return FactorSignal("directional_drift", False, 0.0, "", CONFIRMATION, {"prob_above": None})
    if pa >= 0.54:
        direction, fired = BULLISH, True
    elif pa <= 0.46:
        direction, fired = BEARISH, True
    else:
        direction, fired = "", False
    return FactorSignal("directional_drift", fired, round(min(1.0, abs(pa - 0.5) / 0.5), 3),
                        direction, CONFIRMATION, {"prob_above": pa})


@register("pcr_confirmation")
def pcr_confirmation(ctx) -> FactorSignal:
    """Put-call ratio as a weak contrarian sentiment confirmation. CONFIRMATION-only."""
    pcr = ctx.pcr_oi
    if pcr is None:
        return FactorSignal("pcr_confirmation", False, 0.0, "", CONFIRMATION, {"pcr_oi": None})
    if pcr >= 1.3:
        direction, fired = BULLISH, True   # put-heavy → supportive
    elif pcr <= 0.7:
        direction, fired = BEARISH, True   # call-heavy → cap
    else:
        direction, fired = "", False
    return FactorSignal("pcr_confirmation", fired, round(min(1.0, abs(pcr - 1.0)), 3),
                        direction, CONFIRMATION, {"pcr_oi": pcr})
