"""The unified Buyer Decision Brief — environment-gate → strike-action.

This is the felt product: one read per underlying that answers *whether to play and which strike*.
  1. ENVIRONMENT BAND (go/no-go): VRP (is buying premium even +EV?) + regime (agreement) + the
     event/IV-crush window → a verdict FAVORABLE / NEUTRAL / UNFAVORABLE / ABSTAIN. Abstention is the
     honest default; every non-FAVORABLE verdict carries a `flip_condition` (C10) — what would move it.
  2. STRIKE-ACTION (the lead read): VRP-adjusted physical P(touch K within T) per candidate strike
     (the live vrp_ratio = forecast_RV/ATM_IV feeds the physical read, C2). When the environment is
     non-FAVORABLE the strikes render muted — abstain first, act rarely.

Honest by construction: "analytics, not edge-proven"; the probabilities are model estimates whose
calibration accrues in the ledger; abstention is prominent. No advice.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..config import SETTINGS
from ..ingest.events import days_to_next_event
from .realized_vol_forecast import har_rv_forecast, vrp, vrp_ratio_for_touch
from .regime_score import regime_score
from .term_structure import crush_window, expected_move_from_straddle, iv_term_structure
from .touch_probability import touch_for_dist

DISCLAIMER = (
    "Decision context — analytics, not edge-proven. Probabilities are VRP-adjusted model estimates "
    "whose live calibration accrues on the reliability curve. Not investment advice."
)

FAVORABLE, NEUTRAL, UNFAVORABLE, ABSTAIN = "FAVORABLE", "NEUTRAL", "UNFAVORABLE", "ABSTAIN"


@dataclass
class DecisionBrief:
    underlying: str
    as_of: str
    spot: float
    horizon_days: int
    verdict: str
    flip_condition: str | None
    environment: dict
    strikes: list[dict] = field(default_factory=list)
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> dict:
        return asdict(self)


def _verdict(crush: dict, prob_rich: float | None, *, hi: float = 0.62, lo: float = 0.45) -> str:
    if crush.get("abstain"):
        return ABSTAIN
    if prob_rich is None:
        return NEUTRAL
    if prob_rich >= hi:
        return UNFAVORABLE  # premium very likely rich → buying unfavorable
    if prob_rich <= lo:
        return FAVORABLE    # premium likely cheap → buying may be +EV
    return NEUTRAL


def _flip(verdict: str, crush: dict, e_rv: float | None) -> str | None:
    if verdict == FAVORABLE:
        return None
    if verdict == ABSTAIN:
        return f"after {crush.get('event') or 'the event'} clears ({crush.get('reason')})"
    if verdict == UNFAVORABLE:
        tgt = f"~{round(e_rv, 3)}" if e_rv else "the realized-vol forecast"
        return f"VRP compresses — implied IV falls toward {tgt}, or realized vol rises toward implied"
    return "VRP turns cheap (implied below forecast realized) with no event window"


def decision_brief(ctx, *, history_ohlc=None, horizon_days: int = 5, next_chain=None,
                   n_paths: int = 10000, seed: int = 0, calibration=None,
                   cal_source_class: str = "struct_live") -> DecisionBrief:
    """Compose the brief for one ``SignalContext``. ``history_ohlc`` = ascending [(o,h,l,c)] daily
    bars for the underlying (from the Yahoo fetch) → realized-vol forecast + regime; ``next_chain`` =
    the next-expiry chain for the IV term-structure slope (optional)."""
    spot = float(ctx.spot)
    atm_iv = getattr(ctx, "atm_iv", None) or (ctx.dist.atm_iv if getattr(ctx, "dist", None) else None)
    closes = [row[3] for row in (history_ohlc or []) if row and len(row) >= 4]

    # --- VRP (is buying premium +EV?) ---
    rvf = har_rv_forecast(history_ohlc, horizon_days) if history_ohlc else {"e_rv": None, "log_rv_std": 0.45}
    e_rv = rvf.get("e_rv")
    vrp_read = vrp(atm_iv, e_rv, log_rv_std=rvf.get("log_rv_std", 0.45), horizon=horizon_days)
    live_ratio = vrp_ratio_for_touch(atm_iv, e_rv)  # C2 — None → touch falls back to SETTINGS

    # --- term structure + regime + crush window ---
    chains = [ctx.chain] + ([next_chain] if next_chain is not None else [])
    ts = iv_term_structure(chains)
    regime = regime_score(closes, gex_total=getattr(ctx.gex, "total_gex", None) if getattr(ctx, "gex", None) else None,
                          backwardation=ts.get("backwardation"))
    ev = days_to_next_event(getattr(ctx, "timestamp", "") or "")
    days_to_event = ev["days"] if ev else (ctx.event or {}).get("days_to_expiry")
    event_name = ev["name"] if ev else "expiry"
    crush = crush_window(days_to_event=days_to_event, event_name=event_name,
                         backwardation=ts.get("backwardation", False),
                         crush_score=(ctx.crush or {}).get("crush_score"))

    # De-magicked verdict thresholds (config-backed; defaults reproduce the prior 0.62/0.45). When a
    # calibration service is supplied, the raw VRP rich-probability is mapped through the fitted "vrp"
    # calibrator first, and the UNFAVORABLE cutoff can come from the measured risk-coverage threshold.
    # With no fitted struct map (today's state) this is byte-identical to the old behavior.
    prob_rich = vrp_read.get("prob_realized_lt_implied")
    hi, lo = SETTINGS.vrp_unfavorable_hi, SETTINGS.vrp_favorable_lo
    if calibration is not None and prob_rich is not None:
        prob_rich = calibration.calibrate("vrp", prob_rich, source_class=cal_source_class)
        hi = calibration.abstain_threshold("vrp", source_class=cal_source_class, fallback=hi)
    verdict = _verdict(crush, prob_rich, hi=hi, lo=lo)
    flip = _flip(verdict, crush, e_rv)
    muted = verdict in (UNFAVORABLE, ABSTAIN)

    # --- strike-action (lead read) ---
    em = getattr(ctx.dist, "expected_move_1sigma", None) if getattr(ctx, "dist", None) else None
    touch = touch_for_dist(ctx.dist, horizon_days, vrp_ratio=live_ratio, n_paths=n_paths, seed=seed)
    strikes = []
    for k, t in sorted(touch.items()):
        strikes.append({
            "strike": round(k, 2), "dir": t["dir"],
            "p_touch_phys": t["p_touch_phys"], "p_touch_rn": t["p_touch_rn"],
            "distance_pct": round(100.0 * (k - spot) / spot, 2),
            "vrp_ratio_fallback": t["vrp_ratio_fallback"], "muted": muted,
        })

    environment = {
        "verdict": verdict,
        "vrp": vrp_read,
        "regime": regime,
        "term_structure": ts,
        "crush_window": crush,
        "rv_forecast": {"e_rv": e_rv, "method": rvf.get("method"), "horizon": horizon_days},
        "expected_move": round(em, 2) if em else None,
        "expected_move_straddle": expected_move_from_straddle(getattr(ctx, "dist", None)),
        "atm_iv": round(atm_iv, 4) if atm_iv else None,
    }
    return DecisionBrief(
        underlying=ctx.underlying, as_of=getattr(ctx, "timestamp", "") or "", spot=spot,
        horizon_days=horizon_days, verdict=verdict, flip_condition=flip, environment=environment,
        strikes=strikes)
