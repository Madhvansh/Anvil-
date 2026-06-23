"""Candidate generation — run the library, size, finalize conviction + EV, apply the decision
policy (incl. "no-trade"), and rank by expected-edge-per-rupee-at-risk.

``conviction`` is the market-implied ``edge_prob`` nudged (in [0.9, 1.1]) by regime fit and
IV-rank extremity — it stays a calibratable probability (the ledger later checks that conviction
≈ realized win-rate). Sizing always runs off the raw ``edge_prob`` to keep Kelly honest.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import SETTINGS
from .context import SignalContext
from .library import STRATEGIES
from .sizing import SizingConfig, size_units
from .types import BEARISH, BULLISH, LONG_VOL, NEUTRAL, NO_TRADE, SHORT_VOL, TRADE, TradeCandidate


@dataclass
class GenConfig:
    seller_mode: bool
    allow_event_risk: bool
    min_conviction: float
    min_liquidity_oi: float
    max_spread_pct: float
    sizing: SizingConfig

    @classmethod
    def from_settings(cls, s=SETTINGS) -> "GenConfig":
        return cls(
            seller_mode=s.paper_seller_mode,
            allow_event_risk=s.paper_allow_event_risk,
            min_conviction=s.paper_min_conviction,
            min_liquidity_oi=s.paper_min_liquidity_oi,
            max_spread_pct=s.paper_max_spread_pct,
            sizing=SizingConfig.from_settings(s),
        )


def _conviction(ctx: SignalContext, cand: TradeCandidate, edge: float) -> float:
    fit = float(cand.score_components.get("regime_fit", 0.5))
    align = 0.8 + 0.3 * fit  # fit 1.0 -> 1.10 ; 0.5 -> 0.95 ; 0.25 -> 0.875
    iv_factor = 1.0
    if ctx.iv_rank is not None:
        if cand.direction in (NEUTRAL, SHORT_VOL):
            iv_factor = 1.0 + 0.1 * ((ctx.iv_rank - 50.0) / 50.0)  # rich IV favours selling
        elif cand.direction == LONG_VOL:
            iv_factor = 1.0 + 0.1 * ((50.0 - ctx.iv_rank) / 50.0)  # cheap IV favours buying
        iv_factor = min(1.1, max(0.9, iv_factor))
    return float(min(0.99, max(0.0, edge * align * iv_factor)))


def _ev_per_unit(edge: float, max_profit: float | None, max_loss: float, default_ratio: float) -> float:
    win = max_profit if (max_profit and max_profit > 0) else default_ratio * max_loss
    return edge * win - (1.0 - edge) * max_loss


def _cost_per_unit(cand: TradeCandidate) -> float:
    """Modeled round-trip (open+close, all legs) cost for ONE unit of the candidate, in ₹."""
    from ..paper.costs import charges  # lazy: avoids a strategy<->paper import cycle

    lot = int(getattr(cand, "lot_size", 1) or 1)
    total = 0.0
    for leg in cand.legs:
        ref = float(getattr(leg, "ref_price", 0.0) or 0.0)
        if ref <= 0 or lot <= 0:
            continue
        itype = getattr(leg, "instrument_type", "CE")
        open_side = str(leg.side).upper()
        close_side = "SELL" if open_side == "BUY" else "BUY"
        total += charges(open_side, ref, lot, itype).total
        total += charges(close_side, ref, lot, itype).total
    return round(total, 2)


def _safe_sizing_kwargs(ctx, cand: TradeCandidate, validation_store, regime_bucket) -> dict:
    """Phase-4 honest-sizing inputs for ONE candidate (computed only when safe sizing is on).

    All are per-unit (the candidate is still per-unit here, before generation multiplies by units):
    a cost-adjusted payoff, a SPAN-lite margin feasibility cap, the negative-skew regime tag, and the
    naked stress tail for the CVaR cap. Edge-uncertainty shrink is applied ONLY to MEASURED cells
    (n>0) — for unmeasured cells the gate (not sizing) carries the skepticism, so the engine isn't
    silenced on a book that hasn't accrued evidence yet."""
    from ..paper.margin import required_margin  # lazy: avoids a strategy<->paper import cycle

    kw: dict = {
        "regime_kind": cand.regime_kind or None,
        "cost_per_unit": _cost_per_unit(cand),
        "required_margin_per_unit": required_margin(cand, spot=getattr(ctx, "spot", None)),
        "cvar_per_unit": cand.tail_loss_per_unit,  # naked stress tail; None for defined-risk
    }
    if validation_store is not None and regime_bucket:
        rep = validation_store.get(cand.strategy, regime_bucket, ctx.underlying)
        n = int(rep.get("n") or 0) if rep else 0
        if n > 0:
            kw["edge_n"] = n
    return kw


def _decide(ctx: SignalContext, cand: TradeCandidate, cfg: GenConfig, units: int) -> tuple[str, float, list[str]]:
    reasons: list[str] = []
    if units < 1:
        reasons.append("unsizable")
    if cand.conviction < cfg.min_conviction:
        reasons.append("low_conviction")
    if cand.expected_value <= 0:
        reasons.append("negative_ev")
    min_oi = cand.drivers.get("min_oi")
    if min_oi is not None and 0 < min_oi < cfg.min_liquidity_oi:
        reasons.append("illiquid")
    ws = cand.drivers.get("worst_spread_pct")
    if ws is not None and ws > cfg.max_spread_pct:
        reasons.append("wide_spread")
    # Event-risk gate: block genuine expiry-day gamma/pin danger, and long-vol/directional bets
    # taken INTO high event risk. Premium sellers are NOT blocked by high theta-burn — the decay is
    # exactly their edge — but the governor still applies pin/exposure controls at execution time.
    days = ctx.event.get("days_to_expiry", 99)
    high = ctx.event.get("risk_level") == "high"
    adverse_dir = cand.direction in (LONG_VOL, BULLISH, BEARISH)
    if not cfg.allow_event_risk and ((days is not None and days <= 1.0) or (high and adverse_dir)):
        reasons.append("event_risk")
    if not cand.defined_risk and not cfg.seller_mode:
        reasons.append("naked_blocked")
    shortfall = max(0.0, cfg.min_conviction - cand.conviction)
    nts = min(1.0, 0.25 * len(reasons) + shortfall)
    action = NO_TRADE if reasons else TRADE
    return action, round(nts, 3), reasons


def generate_candidates(
    ctx: SignalContext,
    equity: float,
    cfg: GenConfig | None = None,
    strategies: list[str] | None = None,
    *,
    calibration=None,
    cal_source_class: str = "tip_live",
    safe_sizing: bool = False,
    validation_store=None,
    regime_bucket: str | None = None,
) -> list[TradeCandidate]:
    """Return all candidates with their decision-policy verdict set, ranked best-first.

    ``conviction`` stays the RAW ``_conviction`` output (the value the gate's win-rate≥conviction
    check tests — calibrating it would make the gate pass by construction). When a ``calibration``
    service is supplied, the calibrated probability is attached as the DISPLAY field
    ``calibrated_edge_prob`` only; sizing still runs off the raw ``edge_prob``."""
    cfg = cfg or GenConfig.from_settings()
    names = strategies or list(STRATEGIES.keys())

    raw: list[TradeCandidate] = []
    for name in names:
        fn = STRATEGIES.get(name)
        if fn is None:
            continue
        try:
            raw.extend(fn(ctx, cfg))
        except Exception:  # noqa: BLE001 - one strategy erroring must not sink the tick
            continue

    out: list[TradeCandidate] = []
    for cand in raw:
        edge = cand.edge_prob
        ml_unit, mp_unit = cand.max_loss, cand.max_profit
        ev_unit = _ev_per_unit(edge, mp_unit, ml_unit, cfg.sizing.default_payoff_ratio)
        size_kw = _safe_sizing_kwargs(ctx, cand, validation_store, regime_bucket) if safe_sizing else {}
        units, sizing_dict = size_units(ml_unit, edge, mp_unit, equity, cfg.sizing, **size_kw)

        cand.conviction = _conviction(ctx, cand, edge)  # RAW — recorded to the ledger, tested by the gate
        cand.raw_edge_prob = edge
        if calibration is not None and calibration.is_calibrated("conviction", cal_source_class):
            cand.calibrated_edge_prob = calibration.calibrate(
                "conviction", edge, source_class=cal_source_class)
        cand.units = units
        cand.sizing = sizing_dict
        if units >= 1:
            cand.max_loss = round(ml_unit * units, 2)
            cand.max_profit = round(mp_unit * units, 2) if mp_unit is not None else None
            cand.entry_debit_credit = round(cand.entry_debit_credit * units, 2)
            cand.expected_value = round(ev_unit * units, 2)
            for leg in cand.legs:
                leg.lots = units
        else:
            cand.expected_value = round(ev_unit, 2)  # informational (per-unit)

        action, nts, reasons = _decide(ctx, cand, cfg, units)
        cand.action = action
        cand.no_trade_score = nts
        cand.score_components["conviction"] = cand.conviction
        cand.score_components["no_trade_reasons"] = reasons
        cand.score_components["ev_per_unit"] = round(ev_unit, 2)
        out.append(cand)

    out.sort(key=lambda c: (c.action == TRADE, c.rank_score), reverse=True)
    return out
