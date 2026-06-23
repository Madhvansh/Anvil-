"""Anvil Live v2 — position sizing (pure stdlib).

Port of anvil/anvil/strategy/sizing.py: units = min(risk-fraction, fractional-Kelly, exposure,
lot-cap), risk measured by the structure's modeled max_loss per lot (stress-based for naked).

Adversary #11: Kelly assumes the payoff distribution is known and well-behaved — short-vol
violates that (negative skew, fat left tail), so short-vol Kelly is HARD-CAPPED at 0.10 and the
sizing is always also bound by risk-fraction and exposure. No order is ever placed.
"""
from __future__ import annotations

import math

import config

SHORT_VOL_KELLY_CAP = 0.10   # adversary #11: never full/30% Kelly on a negatively-skewed edge


def kelly_fraction_star(edge_prob: float, payoff_ratio: float) -> float:
    """f* = p - (1-p)/b for a bet that wins ``payoff_ratio`` per unit risked."""
    if payoff_ratio <= 0:
        return 0.0
    return max(0.0, float(edge_prob - (1.0 - edge_prob) / payoff_ratio))


def size_units(max_loss_per_lot: float, edge_prob: float, max_profit_per_lot: float | None,
               equity: float, regime_kind: str) -> tuple[int, dict]:
    """Return (units, sizing_dict). units==0 ⇒ unsizable ⇒ no-trade."""
    if max_loss_per_lot <= 0 or equity <= 0:
        return 0, {"reason": "non-positive risk or equity", "units": 0}

    payoff_ratio = (max_profit_per_lot / max_loss_per_lot) if (max_profit_per_lot and max_profit_per_lot > 0) else 1.5
    f_star = kelly_fraction_star(edge_prob, payoff_ratio)

    kelly_frac = config.V2_KELLY_FRACTION
    if regime_kind == "short_vol":
        kelly_frac = min(kelly_frac, SHORT_VOL_KELLY_CAP)

    risk_budget = config.V2_RISK_FRACTION * equity
    kelly_budget = kelly_frac * f_star * equity
    exposure_budget = config.V2_MAX_EXPOSURE_PCT * equity

    by_risk = math.floor(risk_budget / max_loss_per_lot)
    by_kelly = math.floor(kelly_budget / max_loss_per_lot)
    by_exposure = math.floor(exposure_budget / max_loss_per_lot)
    units = max(0, int(min(by_risk, by_kelly, by_exposure, config.V2_MAX_LOTS_PER_UNDERLYING)))

    binding = min({"risk_fraction": by_risk, "kelly": by_kelly, "exposure": by_exposure,
                   "lot_cap": config.V2_MAX_LOTS_PER_UNDERLYING}.items(), key=lambda kv: kv[1])[0]
    return units, {
        "units": units, "payoff_ratio": round(payoff_ratio, 3), "kelly_f_star": round(f_star, 4),
        "kelly_fraction_used": kelly_frac, "risk_budget": round(risk_budget, 2),
        "by_risk": by_risk, "by_kelly": by_kelly, "by_exposure": by_exposure,
        "lot_cap": config.V2_MAX_LOTS_PER_UNDERLYING, "binding": binding,
        "max_loss_per_lot": round(max_loss_per_lot, 2),
    }
