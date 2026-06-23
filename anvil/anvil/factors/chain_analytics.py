"""Chain-analytics factors (Wave 3) — surface the chain-DYNAMICS reads as display-safe ``FactorSignal``s.

Each reads ``ctx.chain`` (+ ``ctx.prev_chain`` for OI-change) via ``engine.chain_dynamics`` and emits a
CONFIRMATION-tier signal (these corroborate; they don't headline alone — skew/blocks/pin are context,
not a certified directional edge). All abstain-safe: a missing read / sub-threshold value → ``fired=False``.
Display/metadata only (they populate signals + ``signals_fired``; they never move conviction/sizing).
"""

from __future__ import annotations

from ..engine import chain_dynamics as cd
from ..strategy.types import BEARISH, BULLISH, NEUTRAL
from .base import CONFIRMATION, FactorSignal, register

SKEW_SLOPE = "skew_slope_extreme"
OI_CHANGE_THRUST = "oi_change_thrust"
SMART_MONEY = "smart_money_block"
ZERO_DTE = "zero_dte_dynamics"

# Skew slope steeper (in |IV per unit log-moneyness|) than this is a fear/greed extreme worth flagging.
_SKEW_STEEP = 0.6
_OI_MIN_STRENGTH = 0.2     # net OI-change tilt must be at least this one-sided to fire
_PIN_BAND = 0.004          # 0DTE pin fires when spot is within this fraction of max-pain


def _abstain(name: str, reason: str) -> FactorSignal:
    return FactorSignal(name, False, 0.0, "", CONFIRMATION, {"reason": reason})


@register(SKEW_SLOPE)
def skew_slope_extreme(ctx) -> FactorSignal:
    """Fitted IV-smile slope at an extreme = lopsided fear (steep put skew) or greed (call skew). A
    risk-context flag (direction-less); steepness drives the strength."""
    chain = getattr(ctx, "chain", None)
    if chain is None:
        return _abstain(SKEW_SLOPE, "no_chain")
    read = cd.iv_skew_slope(chain)
    if read is None:
        return _abstain(SKEW_SLOPE, "insufficient_iv")
    steep = abs(read["slope"])
    if steep < _SKEW_STEEP:
        return FactorSignal(SKEW_SLOPE, False, 0.0, "", CONFIRMATION,
                            {"slope": read["slope"], "curvature": read["curvature"]})
    strength = max(0.0, min(1.0, steep / (2.0 * _SKEW_STEEP)))
    side = "put_skew" if read["slope"] < 0 else "call_skew"
    return FactorSignal(SKEW_SLOPE, True, float(strength), NEUTRAL, CONFIRMATION,
                        {"slope": read["slope"], "curvature": read["curvature"],
                         "side": side, "atm_iv": read["atm_iv"]})


@register(OI_CHANGE_THRUST)
def oi_change_thrust(ctx) -> FactorSignal:
    """Net directional bias from per-strike OI CHANGE (put-build = support/bullish, call-build =
    resistance/bearish). Needs ``row.oi_change`` or a ``ctx.prev_chain`` to diff against."""
    chain = getattr(ctx, "chain", None)
    if chain is None:
        return _abstain(OI_CHANGE_THRUST, "no_chain")
    read = cd.oi_change_bias(chain, getattr(ctx, "prev_chain", None))
    if read is None:
        return _abstain(OI_CHANGE_THRUST, "no_oi_change")
    if read["bias"] == "neutral" or read["strength"] < _OI_MIN_STRENGTH:
        return FactorSignal(OI_CHANGE_THRUST, False, 0.0, "", CONFIRMATION, {"net": read["net"]})
    direction = BULLISH if read["bias"] == "bullish" else BEARISH
    return FactorSignal(OI_CHANGE_THRUST, True, float(read["strength"]), direction, CONFIRMATION,
                        {"net": read["net"], "call_build": read["call_build"], "put_build": read["put_build"]})


@register(SMART_MONEY)
def smart_money_block(ctx) -> FactorSignal:
    """Unusually large volume at one or more strikes (cross-sectional z-score outliers) — possible
    informed/block activity. Direction-less context (call-heavy vs put-heavy tilt in drivers)."""
    chain = getattr(ctx, "chain", None)
    if chain is None:
        return _abstain(SMART_MONEY, "no_chain")
    read = cd.smart_money_blocks(chain)
    if read is None:
        return _abstain(SMART_MONEY, "insufficient_strikes")
    if not read["n_blocks"]:
        return FactorSignal(SMART_MONEY, False, 0.0, "", CONFIRMATION, {"n_blocks": 0})
    strength = max(0.0, min(1.0, read["n_blocks"] / 5.0))
    return FactorSignal(SMART_MONEY, True, float(strength), NEUTRAL, CONFIRMATION,
                        {"n_blocks": read["n_blocks"], "tilt": read["tilt"],
                         "blocks": read["blocks"][:5]})


@register(ZERO_DTE)
def zero_dte_dynamics(ctx) -> FactorSignal:
    """Expiry-day pin: on 0DTE/expiry-week with spot hugging max-pain, expect a pull toward the pin
    (NEUTRAL). Abstains away from expiry or when spot is far from max-pain."""
    chain = getattr(ctx, "chain", None)
    if chain is None:
        return _abstain(ZERO_DTE, "no_chain")
    read = cd.zero_dte_dynamics(chain, getattr(ctx, "T", None))
    if not read["is_expiry_week"] or read["pin_distance"] is None:
        return FactorSignal(ZERO_DTE, False, 0.0, "", CONFIRMATION, {"dte": read["dte"]})
    if read["pin_distance"] > _PIN_BAND:
        return FactorSignal(ZERO_DTE, False, 0.0, "", CONFIRMATION,
                            {"dte": read["dte"], "pin_distance": read["pin_distance"]})
    strength = max(0.0, min(1.0, 1.0 - read["pin_distance"] / _PIN_BAND))
    return FactorSignal(ZERO_DTE, True, float(strength), NEUTRAL, CONFIRMATION,
                        {"dte": read["dte"], "max_pain": read["max_pain"],
                         "pin_distance": read["pin_distance"], "is_0dte": read["is_0dte"]})
