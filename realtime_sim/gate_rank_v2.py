"""Anvil Live v2 — gate, sizing wiring, ranking, portfolio cap (pure stdlib).

Turns scored structures into ranked, sized trade IDEAS with an honest status:

  ACTIONABLE  — passes the gate AND its (strategy,regime) cell has MEASURED edge clearing the bar.
  WATCH       — passes the gate but edge is not yet measured (the default for a fresh book).
  ABSTAIN     — fails the gate (negative net EV, low POP, illiquid, wrong regime, unsizable, ...).

Honesty rails baked in:
  * conviction stays RAW (the structure's physical POP) into the gate and Kelly — calibrated value
    is DISPLAY-ONLY and never referenced here (adversary #4 / no-gate-circularity).
  * regime_fit gates the family: short-vol only fires in pinning/neutral regimes, long-vol/trend
    only in trend/neutral — so we never sell premium into a runaway move (adversary #15 soft-tilt).
  * a PORTFOLIO correlated cap limits total short-vol STRESS exposure across NIFTY/BANKNIFTY/SENSEX,
    which all gap together (adversary #11).
"""
from __future__ import annotations

import config
import costs_v2
import sizing_v2
from structures_v2 import Structure


def _ev_net_position(s: Structure, units: int) -> float:
    """Position net-EV with cost computed at the ACTUAL units, so the flat per-order brokerage is
    charged once (not ×units). Matches the realized-P&L cost path; consistent for units==1."""
    if units <= 0:
        return 0.0
    pos_cost = costs_v2.round_trip_cost(s.legs, s.lot_size, units)["total"]
    return round(s.ev_gross * units - pos_cost, 2)


def regime_fit(regime: str, regime_kind: str) -> float:
    if regime_kind == "short_vol":
        return {"positive_gamma_mean_revert": 1.0, "neutral_mixed": 0.55}.get(regime, 0.25)
    if regime_kind == "long_vol":
        return {"negative_gamma_trend_amplify": 1.0, "neutral_mixed": 0.55}.get(regime, 0.25)
    if regime_kind == "trend":
        return {"negative_gamma_trend_amplify": 1.0, "neutral_mixed": 0.5}.get(regime, 0.3)
    return 0.5


def evaluate(s: Structure, ms, equity: float, edge_verified_fn) -> dict:
    """Gate + size a single structure. ``edge_verified_fn(strategy, regime)`` → bool (from tracker)."""
    rf = regime_fit(ms.regime, s.regime_kind)
    units, sizing = sizing_v2.size_units(s.max_loss, s.edge_prob, s.max_profit, equity, s.regime_kind)

    reasons = []
    if not (config.V2_MIN_DAYS_TO_EXPIRY <= ms.days_to_expiry <= config.V2_MAX_DAYS_TO_EXPIRY):
        reasons.append(f"expiry {ms.days_to_expiry:.1f}d outside [{config.V2_MIN_DAYS_TO_EXPIRY},{config.V2_MAX_DAYS_TO_EXPIRY}]")
    if s.ev_net <= 0:
        reasons.append("negative net EV after costs")
    if s.edge_prob < config.V2_MIN_POP:
        reasons.append(f"POP {s.edge_prob:.2f} < {config.V2_MIN_POP}")
    if s.ev_on_risk < config.V2_MIN_EV_ON_RISK:
        reasons.append(f"EV/risk {s.ev_on_risk:.3f} < {config.V2_MIN_EV_ON_RISK}")
    if rf < 0.5:
        reasons.append(f"regime '{ms.regime}' unfit for {s.regime_kind} (fit {rf:.2f})")
    if s.liquidity < 0.25 or s.min_oi < 1000:
        reasons.append(f"illiquid (liq {s.liquidity:.2f}, min_oi {int(s.min_oi)})")
    if s.worst_spread_pct is not None and s.worst_spread_pct > 0.08:
        reasons.append(f"wide spread {s.worst_spread_pct:.0%}")
    if units <= 0:
        reasons.append(f"unsizable (binding={sizing.get('binding')})")
    if s.regime_kind == "short_vol" and ms.vrp_signal == "BUY_VOL":
        reasons.append("VRP inverted (implied cheap) — don't sell premium")

    if reasons:
        status, action = "ABSTAIN", "NO_TRADE"
    elif edge_verified_fn(s.strategy, ms.regime):
        status, action = "ACTIONABLE", "TRADE"
    else:
        status, action = "WATCH", "TRADE"

    # ranking score: only meaningful for TRADE-eligible; rewards regime-aligned, high EV-on-risk, high POP
    score = (rf * s.ev_on_risk * s.edge_prob) if action == "TRADE" else -1.0
    return {
        "structure": s, "regime_fit": round(rf, 3), "units": units, "sizing": sizing,
        "status": status, "action": action, "gate_reasons": reasons, "score": round(score, 5),
        "ev_net_position": _ev_net_position(s, units), "max_loss_position": round(s.max_loss * units, 2),
        "edge_verified": status == "ACTIONABLE",
    }


def apply_portfolio_cap(evals: list[dict], equity: float) -> list[dict]:
    """Adversary #11: short-vol legs across indices gap together. Cap TOTAL short-vol stress
    max-loss at V2_MAX_EXPOSURE_PCT of equity; downsize/drop the lowest-ranked over the cap."""
    cap = config.V2_MAX_EXPOSURE_PCT * equity
    short_vol = sorted([e for e in evals if e["action"] == "TRADE" and e["structure"].regime_kind == "short_vol"],
                       key=lambda e: e["score"], reverse=True)
    running = 0.0
    for e in short_vol:
        ml = e["max_loss_position"]
        if running + ml > cap and e["units"] > 0:
            # shrink units to fit; if none fit, abstain
            room = max(0.0, cap - running)
            per_lot = e["structure"].max_loss
            fit_units = int(room // per_lot) if per_lot > 0 else 0
            if fit_units <= 0:
                e["status"], e["action"], e["score"] = "ABSTAIN", "NO_TRADE", -1.0
                e["gate_reasons"] = e["gate_reasons"] + ["portfolio short-vol stress cap reached"]
                e["units"] = 0
                e["ev_net_position"] = 0.0
                e["max_loss_position"] = 0.0
                continue
            e["units"] = fit_units
            e["ev_net_position"] = _ev_net_position(e["structure"], fit_units)
            e["max_loss_position"] = round(per_lot * fit_units, 2)
            e["gate_reasons"] = e["gate_reasons"] + ["downsized by portfolio short-vol stress cap"]
        running += e["max_loss_position"]
    return evals


def rank(evals: list[dict]) -> list[dict]:
    trade = [e for e in evals if e["action"] == "TRADE" and e["units"] > 0]
    return sorted(trade, key=lambda e: e["score"], reverse=True)
