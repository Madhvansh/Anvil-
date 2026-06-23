"""Momentum factors — multi-timeframe trend + options-flow velocity over the SignalContext.

These read the optional time-series blocks computed on the context (``ctx.momentum`` from
``engine.momentum``; ``ctx.flow`` from ``engine.flow_momentum``; ``ctx.intraday_session`` for
opening-range/VWAP/last-30-min). Each emits the SAME ``FactorSignal`` the option/equity factors do, so
momentum flows through the existing conviction → tip → ledger → validation spine unchanged.

Honest tiering: multi-timeframe trend alignment and dealer-gamma flips are STRONG (replicated /
economically grounded); OI-velocity, IV-rank velocity and the india-unvalidated intraday signals are
CONFIRMATION-only until the live reliability curve + a cert cell back them. Every factor ABSTAINS
(``fired=False``) when its time-series block is absent — so the legacy chain-only path is unaffected.
"""

from __future__ import annotations

from ..engine import momentum as mom
from ..strategy.types import BEARISH, BULLISH, NEUTRAL
from .base import CONFIRMATION, STRONG, FactorSignal, register

MTF_TREND = "mtf_trend"
OI_VELOCITY = "oi_velocity_thrust"
GEX_FLIP = "gex_flip_momentum"
IV_RANK_VEL = "iv_rank_velocity"
INTRADAY_ORVWAP = "intraday_or_vwap"
EXPIRY_LAST30 = "expiry_last30_gamma"


def _abstain(name: str, tier: str, reason: str) -> FactorSignal:
    return FactorSignal(name, False, 0.0, "", tier, {"reason": reason})


@register(MTF_TREND)
def mtf_trend(ctx) -> FactorSignal:
    """Consensus time-series momentum across timeframes (minutes→weeks). STRONG when the timeframes
    agree on a direction with a clean (vol-normalized) trend; abstains on conflict or no data."""
    read = getattr(ctx, "momentum", None)
    if read is None:
        return _abstain(MTF_TREND, STRONG, "no_momentum_data")
    if read.direction == NEUTRAL or read.strength <= 0:
        return FactorSignal(MTF_TREND, False, 0.0, "", STRONG,
                            {"agreement": read.agreement, "n_timeframes": read.n_timeframes})
    return FactorSignal(MTF_TREND, True, float(read.strength), read.direction, STRONG,
                        {"agreement": read.agreement, "n_timeframes": read.n_timeframes,
                         "per_tf": read.per_tf})


@register(GEX_FLIP)
def gex_flip_momentum(ctx) -> FactorSignal:
    """Dealer gamma crossing zero (pinning ↔ trending regime change) — the most actionable flow event.
    Direction is volatility-regime (LONG_VOL into negative gamma, SHORT_VOL into positive). STRONG."""
    flow = getattr(ctx, "flow", None)
    if flow is None or not flow.gex:
        return _abstain(GEX_FLIP, STRONG, "no_flow_data")
    g = flow.gex
    if not g.get("flip"):
        return FactorSignal(GEX_FLIP, False, 0.0, "", STRONG, {"now_negative_gamma": g.get("now_negative_gamma")})
    return FactorSignal(GEX_FLIP, True, float(g.get("strength") or 1.0), g.get("direction") or NEUTRAL,
                        STRONG, {"flip": True, "now_negative_gamma": g.get("now_negative_gamma")})


@register(OI_VELOCITY)
def oi_velocity_thrust(ctx) -> FactorSignal:
    """Pace of open-interest participation (fresh positioning building). Direction-less (corroborates
    that a move has real participation behind it) → CONFIRMATION."""
    flow = getattr(ctx, "flow", None)
    if flow is None or not flow.oi:
        return _abstain(OI_VELOCITY, CONFIRMATION, "no_flow_data")
    oi = flow.oi
    if not oi.get("fired"):
        return FactorSignal(OI_VELOCITY, False, 0.0, "", CONFIRMATION, {"change": oi.get("change")})
    return FactorSignal(OI_VELOCITY, True, float(oi.get("strength") or 0.0), "", CONFIRMATION,
                        {"building": oi.get("building"), "change": oi.get("change")})


@register(IV_RANK_VEL)
def iv_rank_velocity(ctx) -> FactorSignal:
    """IV-rank getting richer (SHORT_VOL) or cheaper (LONG_VOL) over the recorded window. CONFIRMATION."""
    flow = getattr(ctx, "flow", None)
    if flow is None or not flow.iv_rank:
        return _abstain(IV_RANK_VEL, CONFIRMATION, "no_flow_data")
    ivr = flow.iv_rank
    if not ivr.get("fired"):
        return FactorSignal(IV_RANK_VEL, False, 0.0, "", CONFIRMATION, {"change_points": ivr.get("change_points")})
    return FactorSignal(IV_RANK_VEL, True, float(ivr.get("strength") or 0.0), ivr.get("direction") or NEUTRAL,
                        CONFIRMATION, {"change_points": ivr.get("change_points")})


@register(INTRADAY_ORVWAP)
def intraday_or_vwap(ctx) -> FactorSignal:
    """Opening-range breakout confirmed by the price's side of session VWAP. CONFIRMATION (intraday,
    india-unvalidated). Needs ``ctx.intraday_session`` with highs/lows/prices/volumes/last."""
    sess = getattr(ctx, "intraday_session", None)
    if not sess:
        return _abstain(INTRADAY_ORVWAP, CONFIRMATION, "no_intraday_session")
    last = sess.get("last")
    orb = mom.or_breakout(sess.get("highs", []), sess.get("lows", []), last,
                          first_n=int(sess.get("or_bars", 3)))
    vwr = mom.vwap_reversion(sess.get("prices", []), sess.get("volumes", []), last)
    if orb is None or not orb.get("fired"):
        return FactorSignal(INTRADAY_ORVWAP, False, 0.0, "", CONFIRMATION, {"reason": "no_breakout"})
    # Confirm only when VWAP agrees with the breakout side.
    if vwr is not None:
        agree = (orb["direction"] == BULLISH and vwr["above"]) or (orb["direction"] == BEARISH and not vwr["above"])
        if not agree:
            return FactorSignal(INTRADAY_ORVWAP, False, 0.0, "", CONFIRMATION, {"reason": "vwap_disagrees"})
    return FactorSignal(INTRADAY_ORVWAP, True, float(orb.get("strength") or 0.0), orb["direction"],
                        CONFIRMATION, {"or_high": orb.get("or_high"), "or_low": orb.get("or_low")})


@register(EXPIRY_LAST30)
def expiry_last30_gamma(ctx) -> FactorSignal:
    """Baltussen last-30-min expiry-day gamma drift (negative gamma → late-session continuation).
    CONFIRMATION + india-unvalidated. Needs ``ctx.intraday_session.returns`` + dealer-gamma sign."""
    sess = getattr(ctx, "intraday_session", None)
    if not sess or "returns" not in sess:
        return _abstain(EXPIRY_LAST30, CONFIRMATION, "no_intraday_returns")
    gex = getattr(ctx, "gex", None)
    gex_sign = -1 if (gex is not None and getattr(gex, "total_gex", 0.0) < 0) else 1
    dte = int(sess.get("days_to_expiry", 99))
    read = mom.last30_expiry_gamma_drift(sess["returns"], gex_sign, days_to_expiry=dte)
    if read is None or not read.get("fired"):
        return FactorSignal(EXPIRY_LAST30, False, 0.0, "", CONFIRMATION, {"reason": "not_negative_gamma_expiry"})
    return FactorSignal(EXPIRY_LAST30, True, 0.5, read["direction"], CONFIRMATION,
                        {"rest_of_day_return": read.get("rest_of_day_return"), "note": read.get("note")})
