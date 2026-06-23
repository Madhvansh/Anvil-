"""Project a (private) strategy ``TradeCandidate`` into a (public) ``Tip``.

This is the single sanctioned bridge from the strategy engine to the public tip surface. It adds
two things the candidate lacks: a realistic ROUND-TRIP cost (open + close, both legs, via the India
F&O charge stack in ``paper.costs``) so the tip's EV is honest after costs, and a light compliance
scrub of free-text fields (guarantee / performance-claim language only — a structured tip
legitimately contains entry/target/stop). Pure; no I/O.
"""

from __future__ import annotations

from ..agent.guardrail import check_compliance
from ..factors.regime_gate import classify_regime
from ..paper.costs import charges
from .types import WATCHLIST, Tip

# Free-text in a tip may describe the trade, but must never promise outcomes or cite an accuracy
# figure (accuracy is only ever the live ledger metric). We scrub these two label classes.
_BANNED_TEXT_LABELS = frozenset({"guarantee", "performance_claim"})
_SCRUBBED = "(rationale withheld: failed compliance scrub)"

_TARGET_KEYS = ("target", "target_level", "take_profit", "tp", "target_price")
_STOP_KEYS = ("stop", "stop_level", "stop_loss", "sl", "stop_price")


def _first_num(d: dict | None, keys) -> float | None:
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return None


def _scrub(text: str) -> str:
    if not text:
        return ""
    if _BANNED_TEXT_LABELS.intersection(check_compliance(text)):
        return _SCRUBBED
    return text


def round_trip_cost(cand) -> float:
    """Modeled open+close charges for every leg (₹, all sized units). Uses each leg's ref_price as
    the fill estimate for both open and close — a coarse, slightly conservative round-trip cost."""
    total = 0.0
    lot_size = int(getattr(cand, "lot_size", 1) or 1)
    for leg in cand.legs:
        lots = abs(int(getattr(leg, "lots", 0) or 0))
        qty = lots * lot_size
        ref = float(getattr(leg, "ref_price", 0.0) or 0.0)
        if qty <= 0 or ref <= 0:
            continue
        itype = getattr(leg, "instrument_type", "CE")
        open_side = str(leg.side).upper()
        close_side = "SELL" if open_side == "BUY" else "BUY"
        total += charges(open_side, ref, qty, itype).total
        total += charges(close_side, ref, qty, itype).total
    return round(total, 2)


def tip_from_candidate(
    cand,
    ctx=None,
    signals_fired: list[str] | None = None,
    source: str = "tip_live",
    tier: str = WATCHLIST,
    created_ts: str | None = None,
    resolve_ts: str | None = None,
    regime_bucket: str | None = None,
) -> Tip:
    """Build a ``Tip`` from a sized ``TradeCandidate`` and its ``SignalContext``.

    ``ctx`` supplies created_ts/resolve_ts/regime when not passed explicitly. ``regime_bucket`` is
    the gate cell key — passed in by the pipeline, else derived from ``ctx``. ``tier`` defaults to
    WATCHLIST — only the validation gate promotes a tip to HEADLINE.
    """
    cost = round_trip_cost(cand)
    gross_ev = float(getattr(cand, "expected_value", 0.0) or 0.0)
    exit_rules = getattr(cand, "exit_rules", None) or {}

    regime_label = ""
    if ctx is not None and getattr(ctx, "regime", None) is not None:
        regime_label = str(getattr(ctx.regime, "label", "") or "")
    bucket = regime_bucket if regime_bucket is not None else (classify_regime(ctx) if ctx is not None else "")

    created = created_ts or (getattr(ctx, "timestamp", None) if ctx else None) or ""
    resolve = resolve_ts or (getattr(ctx, "expiry", None) if ctx else None) or created

    return Tip(
        underlying=cand.underlying,
        created_ts=created,
        resolve_ts=resolve,
        horizon_days=float(getattr(cand, "horizon_days", 0.0) or 0.0),
        structure=cand.strategy,
        direction=cand.direction,
        legs=[leg.to_dict() for leg in cand.legs],
        lot_size=int(getattr(cand, "lot_size", 1) or 1),
        conviction=float(getattr(cand, "conviction", 0.0) or 0.0),
        edge_prob=float(getattr(cand, "edge_prob", 0.0) or 0.0),
        calibrated_edge_prob=getattr(cand, "calibrated_edge_prob", None),
        raw_edge_prob=getattr(cand, "raw_edge_prob", None),
        gross_ev=gross_ev,
        round_trip_cost=cost,
        cost_adjusted_ev=round(gross_ev - cost, 2),
        max_loss=float(getattr(cand, "max_loss", 0.0) or 0.0),
        max_profit=getattr(cand, "max_profit", None),
        entry_debit_credit=float(getattr(cand, "entry_debit_credit", 0.0) or 0.0),
        breakevens=list(getattr(cand, "breakevens", None) or []),
        probability_band=getattr(cand, "probability_band", None),
        target=_first_num(exit_rules, _TARGET_KEYS),
        stop=_first_num(exit_rules, _STOP_KEYS),
        target_rule=getattr(cand, "target_exit", "") or "",
        stop_rule=getattr(cand, "stop_exit", "") or "",
        signals_fired=list(signals_fired or []),
        regime_at_issue=regime_label,
        regime_bucket=bucket,
        tier=tier,
        source=source,
        rationale=_scrub(getattr(cand, "rationale", "") or getattr(cand, "entry_reason", "")),
        invalidation=_scrub(getattr(cand, "invalidation_condition", "") or ""),
    )
