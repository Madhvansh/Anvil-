"""Position sizing — aggressive ``min(risk-fraction, fractional-Kelly, …)``, capped and lot-floored.

Risk is always measured by the candidate's modeled ``max_loss`` per unit (finite even for naked
structures, where it comes from a modeled stop / CVaR true tail — see ``strategy.tail``). So the
same formula sizes defined- and undefined-risk trades identically. Pure functions — no I/O.

Phase 4 adds four honest-sizing safeguards, each OFF unless its per-call input is supplied (so old
call sites stay byte-identical):
  * edge-uncertainty shrink — shrink the Kelly edge toward 0.5 by ``z`` sampling-error haircuts,
    given the resolved sample count ``edge_n`` (an unmeasured edge can't be Kelly-sized);
  * CVaR/tail cap — a fourth binding term from a per-unit tail loss ``cvar_per_unit``;
  * broker-margin feasibility cap — a fifth binding term from ``required_margin_per_unit`` so the
    sized number is always placeable (it agrees with ``paper.governor``);
  * short-vol Kelly hard cap — negatively-skewed premium selling never sizes on full Kelly.
Cost-adjusted EV: when ``cost_per_unit`` is given, Kelly's payoff ratio is netted of the round-trip
cost so sizing matches the cost-net number the gate and ledger resolve against.

The shrink/shrunk edge is used for the Kelly term ONLY — the displayed ``edge_prob``/``conviction``
are never modified (calibration honesty: sizing runs off the raw, uncertainty-discounted edge).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..config import SETTINGS


@dataclass
class SizingConfig:
    risk_fraction: float  # max modeled loss per trade as a fraction of equity
    kelly_fraction: float  # fractional Kelly multiplier
    max_exposure_pct: float  # single-trade exposure cap (fraction of equity)
    max_lots_per_underlying: int  # absolute cap on units (≈ lots of the primary leg)
    default_payoff_ratio: float = 1.5  # used when max_profit is undefined (long-vol upside)
    # --- Phase 4 knobs. Dataclass defaults are NO-OP; ``from_settings`` carries the live values. ---
    edge_shrink_z: float = 0.0  # SE haircuts on the Kelly edge (0 => no shrink)
    cvar_budget_pct: float = 0.0  # CVaR-cap budget as a fraction of equity (0 => term off)
    cvar_sigma_divisor: float = 2.0  # parametric tail helper: sigma ≈ max_loss / divisor
    short_vol_kelly_cap: float = 1.0  # hard cap on the Kelly fraction for short-vol (1.0 => no cap)
    tail_z: float = 2.06  # Normal CVaR-95 multiplier for the true-tail max-loss

    @classmethod
    def from_settings(cls, s=SETTINGS) -> "SizingConfig":
        """The single canonical construction — one field set for the option and equity engines."""
        return cls(
            risk_fraction=s.paper_risk_fraction,
            kelly_fraction=s.paper_kelly_fraction,
            max_exposure_pct=s.paper_max_exposure_pct,
            max_lots_per_underlying=s.paper_max_lots_per_underlying,
            edge_shrink_z=s.paper_edge_shrink_z,
            cvar_budget_pct=s.paper_cvar_budget_pct,
            cvar_sigma_divisor=s.paper_cvar_sigma_divisor,
            short_vol_kelly_cap=s.paper_short_vol_kelly_cap,
            tail_z=s.paper_tail_z,
        )


def kelly_fraction_star(edge_prob: float, payoff_ratio: float) -> float:
    """Kelly fraction f* = p - (1-p)/b for a bet that wins ``payoff_ratio`` per unit risked."""
    if payoff_ratio <= 0:
        return 0.0
    f = edge_prob - (1.0 - edge_prob) / payoff_ratio
    return max(0.0, float(f))


def shrink_edge(edge_prob: float, n: int | None, z: float) -> float:
    """Shrink ``edge_prob`` toward 0.5 by ``z`` standard errors of a proportion estimated from ``n``
    resolutions: ``SE = sqrt(p(1-p)/n)``; ``p_shrunk = 0.5 + sign(p-0.5)·max(0, |p-0.5| - z·SE)``.

    Gating: ``n is None`` OR ``z <= 0`` => shrink is OFF (returns the edge unchanged). ``n <= 0`` with
    ``z > 0`` => an unmeasured edge → fully shrunk to 0.5 (it cannot be Kelly-sized). The result never
    crosses 0.5. As ``n`` grows the haircut shrinks (more evidence → less discount)."""
    if z <= 0 or n is None:
        return edge_prob
    if n <= 0:
        return 0.5
    p = min(1.0, max(0.0, edge_prob))
    se = math.sqrt(max(p * (1.0 - p), 0.0) / n)
    excess = abs(p - 0.5) - z * se
    if excess <= 0:
        return 0.5
    return 0.5 + math.copysign(excess, p - 0.5)


def size_units(
    max_loss_per_unit: float,
    edge_prob: float,
    max_profit_per_unit: float | None,
    equity: float,
    cfg: SizingConfig,
    *,
    edge_n: int | None = None,
    cost_per_unit: float | None = None,
    cvar_per_unit: float | None = None,
    required_margin_per_unit: float | None = None,
    regime_kind: str | None = None,
) -> tuple[int, dict]:
    """Return ``(units, sizing_dict)``; ``units == 0`` means the trade can't be sized → no-trade.

    Every keyword arg is optional and OFF by default: with none supplied the result is identical to
    the pre-Phase-4 ``min(by_risk, by_kelly, by_exposure, lot_cap)`` on the gross payoff ratio."""
    if max_loss_per_unit <= 0 or equity <= 0:
        return 0, {"reason": "non-positive risk or equity", "units": 0}

    # Edge-uncertainty shrink — Kelly input only; the displayed edge is never modified.
    edge_for_kelly = shrink_edge(edge_prob, edge_n, cfg.edge_shrink_z)

    # Payoff ratio: cost-adjusted (net of the round-trip cost) when a per-unit cost is supplied.
    if cost_per_unit and cost_per_unit > 0:
        cost = float(cost_per_unit)
        gross_win = max_profit_per_unit if (max_profit_per_unit and max_profit_per_unit > 0) \
            else cfg.default_payoff_ratio * max_loss_per_unit
        payoff_ratio = max(0.0, gross_win - cost) / (max_loss_per_unit + cost)
    elif max_profit_per_unit and max_profit_per_unit > 0:
        payoff_ratio = max_profit_per_unit / max_loss_per_unit
    else:
        payoff_ratio = cfg.default_payoff_ratio

    f_star = kelly_fraction_star(edge_for_kelly, payoff_ratio)

    # Short-vol Kelly hard cap — negative-skew guard (premium selling never sizes on full Kelly).
    kelly_frac = cfg.kelly_fraction
    if regime_kind == "short_vol":
        kelly_frac = min(kelly_frac, cfg.short_vol_kelly_cap)

    risk_budget = cfg.risk_fraction * equity
    kelly_budget = kelly_frac * f_star * equity
    exposure_budget = cfg.max_exposure_pct * equity

    units_by_risk = math.floor(risk_budget / max_loss_per_unit)
    units_by_kelly = math.floor(kelly_budget / max_loss_per_unit)
    units_by_exposure = math.floor(exposure_budget / max_loss_per_unit)

    caps: dict[str, int] = {
        "risk_fraction": units_by_risk,
        "kelly": units_by_kelly,
        "exposure": units_by_exposure,
        "lot_cap": int(cfg.max_lots_per_underlying),
    }

    # CVaR/tail cap — a fourth binding term from a per-unit tail loss (e.g. mc_pnl CVaR for naked).
    units_by_cvar: int | None = None
    if cvar_per_unit is not None and cvar_per_unit > 0 and cfg.cvar_budget_pct > 0:
        units_by_cvar = math.floor(cfg.cvar_budget_pct * equity / cvar_per_unit)
        caps["cvar"] = units_by_cvar

    # Broker-margin feasibility cap — so the sized number is always placeable (agrees with governor).
    units_by_margin: int | None = None
    if required_margin_per_unit is not None and required_margin_per_unit > 0:
        units_by_margin = math.floor(cfg.max_exposure_pct * equity / required_margin_per_unit)
        caps["margin"] = units_by_margin

    units = max(0, int(min(caps.values())))

    info: dict = {
        "units": units,
        "payoff_ratio": round(payoff_ratio, 3),
        "kelly_f_star": round(f_star, 4),
        "kelly_fraction_used": round(kelly_frac, 4),
        "risk_budget": round(risk_budget, 2),
        "kelly_budget": round(kelly_budget, 2),
        "max_loss_per_unit": round(max_loss_per_unit, 2),
        "units_by_risk": units_by_risk,
        "units_by_kelly": units_by_kelly,
        "units_by_exposure": units_by_exposure,
        "cap_lots": int(cfg.max_lots_per_underlying),
        "binding": min(caps, key=caps.get),
    }
    if edge_n is not None:
        info["edge_shrunk"] = round(edge_for_kelly, 4)
        info["edge_n"] = int(edge_n)
    if cost_per_unit:
        info["cost_per_unit"] = round(float(cost_per_unit), 2)
    if units_by_cvar is not None:
        info["units_by_cvar"] = units_by_cvar
        info["cvar_per_unit"] = round(float(cvar_per_unit), 2)
    if units_by_margin is not None:
        info["units_by_margin"] = units_by_margin
        info["margin_per_unit"] = round(float(required_margin_per_unit), 2)
    return units, info
