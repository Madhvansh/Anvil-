"""IV term-structure + the event / IV-crush abstention window — half the environment gate.

Front-vs-next-expiry ATM-IV slope tells the buyer whether an event is being priced in: **contango**
(front < next) = calm; **backwardation** (front > next) = an imminent event the front expiry is
pricing → premium is rich and about to crush → *abstain from buying*. Expected move ≈ 0.85×ATM
straddle (the market's own move estimate). Pure functions; reuses `vol.term_structure` + the event
calendar. No new pricing.
"""

from __future__ import annotations

from . import vol as volmod


def iv_term_structure(chains) -> dict:
    """Front/next ATM-IV + slope from ≥2 expiries. ``{front_iv, next_iv, slope, shape, backwardation}``.
    ``slope = (next_iv − front_iv)/front_iv``; backwardation ⇒ slope < 0 ⇒ event imminent."""
    rows = [r for r in volmod.term_structure(chains) if r.get("atm_iv")]
    if len(rows) < 2:
        front = rows[0]["atm_iv"] if rows else None
        return {"front_iv": front, "next_iv": None, "slope": None, "shape": "unknown",
                "backwardation": False, "n_expiries": len(rows)}
    front, nxt = rows[0]["atm_iv"], rows[1]["atm_iv"]
    slope = (nxt - front) / front if front else None
    backwardation = bool(slope is not None and slope < -0.01)
    shape = "backwardation" if backwardation else ("contango" if (slope or 0) > 0.01 else "flat")
    return {"front_iv": round(front, 4), "next_iv": round(nxt, 4),
            "slope": round(slope, 4) if slope is not None else None, "shape": shape,
            "backwardation": backwardation, "n_expiries": len(rows)}


def expected_move_from_straddle(dist) -> float | None:
    """Market's own expected move ≈ 0.85 × ATM straddle price (well-supported rule of thumb)."""
    if dist is None:
        return None
    straddle = float(getattr(dist, "em_straddle", 0.0) or 0.0)
    return round(0.85 * straddle, 2) if straddle > 0 else None


def crush_window(*, days_to_event: float | None, event_name: str | None,
                 backwardation: bool, crush_score: float | None) -> dict:
    """The abstain-from-buying gate: an event within ~3 days OR a high crush score OR front-expiry
    backwardation ⇒ don't buy premium into the crush. ``{abstain, reason, days_to_event, event}``."""
    reasons = []
    near = days_to_event is not None and days_to_event <= 3
    if near:
        reasons.append(f"{event_name or 'event'} in {int(days_to_event)}d")
    if backwardation:
        reasons.append("IV backwardation (front-expiry stress)")
    if crush_score is not None and crush_score >= 66:
        reasons.append(f"high IV-crush score ({int(crush_score)})")
    abstain = bool(reasons)
    return {"abstain": abstain, "reason": "; ".join(reasons) if reasons else "no scheduled crush",
            "days_to_event": days_to_event, "event": event_name, "backwardation": backwardation,
            "crush_score": crush_score}
