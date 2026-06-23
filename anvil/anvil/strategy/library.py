"""Strategy library — declarative, regime-gated converters from analytics to TradeCandidates.

Each strategy is a pure ``(ctx, cfg) -> list[TradeCandidate]`` registered via ``@register(name)``.
Every candidate is priced off REAL chain rows (mids), carries a finite modeled ``max_loss``, a
market-implied ``edge_prob`` (the probability the structure finishes profitable, from the
Breeden-Litzenberger distribution), and the full decision-policy metadata. One "unit" == one lot
per leg; ``generate`` then sizes the number of units.

v1 families (full instrument/structure scope): iron_condor, short_strangle (naked, seller-mode),
put_credit_spread, call_credit_spread, long_straddle, long_strangle, iv_crush_fade, and
directional_future. Stock-option underlyings drop straight in once the instrument master lands.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import SETTINGS
from ..models import OptionType
from .context import SignalContext
from .tail import naked_stress_max_loss
from .types import (
    BEARISH,
    BULLISH,
    LONG_VOL,
    NEUTRAL,
    SHORT_VOL,
    Leg,
    TradeCandidate,
)

STRATEGIES: dict[str, Callable[[SignalContext, object], list[TradeCandidate]]] = {}


def register(name: str):
    def deco(fn: Callable[[SignalContext, object], list[TradeCandidate]]):
        STRATEGIES[name] = fn
        return fn

    return deco


# --- shared helpers ---------------------------------------------------------
def _step(ctx: SignalContext) -> float:
    ks = ctx.strikes()
    gaps = [b - a for a, b in zip(ks, ks[1:]) if b > a]
    return float(min(gaps)) if gaps else 50.0


def _opt_symbol(u: str, strike: float, ot: OptionType, expiry: str) -> str:
    return f"{u}{expiry.replace('-', '')}{int(round(strike))}{ot.value}"


def _opt_leg(ctx: SignalContext, strike: float | None, ot: OptionType, side: str) -> Leg | None:
    if strike is None:
        return None
    mid = ctx.mid(strike, ot)
    if mid is None or mid <= 0:
        return None
    row = ctx.row(strike, ot)
    delta = row.greeks.delta if (row and row.greeks) else None
    return Leg(
        side=side,
        lots=1,
        expiry=ctx.expiry,
        ref_price=float(mid),
        option_type=ot,
        strike=float(strike),
        instrument_type=ot.value,
        delta=delta,
        symbol=_opt_symbol(ctx.underlying, strike, ot, ctx.expiry),
    )


def _net_cashflow(legs: list[Leg], lot_size: int) -> float:
    """Signed cash to OPEN (positive = debit/cash out, negative = credit)."""
    return float(sum(leg.cashflow(lot_size) for leg in legs))


def _liquidity(ctx: SignalContext, legs: list[Leg]) -> tuple[float, float, float | None]:
    """Return (score 0..1, min_oi, worst_spread_pct) across the option legs."""
    ois: list[float] = []
    spreads: list[float] = []
    for leg in legs:
        if leg.option_type is None:
            continue
        oi, sp = ctx.leg_liquidity(leg.strike, leg.option_type)
        ois.append(oi)
        if sp is not None:
            spreads.append(sp)
    min_oi = min(ois) if ois else 0.0
    worst_spread = max(spreads) if spreads else None
    oi_score = min(1.0, min_oi / 100_000.0)
    spread_score = 1.0 if worst_spread is None else max(0.0, 1.0 - worst_spread / 0.10)
    return round(0.6 * oi_score + 0.4 * spread_score, 3), min_oi, worst_spread


def _vol_risk(ctx: SignalContext) -> str:
    order = {"low": 0, "medium": 1, "high": 2}
    a = ctx.crush.get("level", "low")
    b = ctx.event.get("risk_level", "low")
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _regime_fit(ctx: SignalContext, kind: str) -> float:
    """kind: 'short_vol' (premium-selling), 'long_vol', 'trend'."""
    label = ctx.regime.label
    if kind == "short_vol":
        return {"positive_gamma_mean_revert": 1.0, "neutral_mixed": 0.55}.get(label, 0.25)
    if kind == "long_vol":
        return {"negative_gamma_trend_amplify": 1.0, "neutral_mixed": 0.55}.get(label, 0.25)
    if kind == "trend":
        return {"negative_gamma_trend_amplify": 1.0, "neutral_mixed": 0.5}.get(label, 0.3)
    return 0.5


def _make(
    ctx: SignalContext,
    *,
    strategy: str,
    direction: str,
    legs: list[Leg],
    max_loss_per_unit: float,
    max_profit_per_unit: float | None,
    breakevens: list[float],
    edge_prob: float,
    regime_kind: str,
    defined_risk: bool,
    entry_reason: str,
    invalidation: str,
    exit_rules: dict,
    horizon_days: float,
    extra_drivers: dict | None = None,
) -> TradeCandidate | None:
    if not legs or max_loss_per_unit <= 0 or edge_prob != edge_prob:  # NaN guard
        return None
    lot = ctx.chain.lot_size or 1
    entry_dc = _net_cashflow(legs, lot)
    edge_prob = float(min(0.999, max(0.0, edge_prob)))
    liq_score, min_oi, worst_spread = _liquidity(ctx, legs)
    band = ctx.probability_band()

    tp = exit_rules.get("take_profit_pct")
    sl = exit_rules.get("stop_loss_pct")
    target_exit = f"Take profit at {int(tp*100)}% of max-profit" if tp else "Manage at expiry"
    stop_exit = f"Stop at {sl:g}x risk / modeled max-loss" if sl else "Hold to defined max-loss"

    # Naked structures: the real risk is the GAP through the stop, not the stop multiple. Carry a
    # stress (≈3σ) per-unit tail so Phase-4 sizing can cap units against the gap (the modeled
    # ``max_loss`` above stays the EV/stop number — replacing it would corrupt EV).
    tail_loss = None
    if not defined_risk:
        tail_loss = naked_stress_max_loss(legs, lot, ctx.spot, ctx.expected_move)

    return TradeCandidate(
        strategy=strategy,
        underlying=ctx.underlying,
        direction=direction,
        legs=legs,
        lot_size=lot,
        edge_prob=edge_prob,
        conviction=edge_prob,  # finalized (regime/IV-adjusted) in generate.py
        entry_debit_credit=round(entry_dc, 2),
        max_loss=round(max_loss_per_unit, 2),
        max_profit=(round(max_profit_per_unit, 2) if max_profit_per_unit is not None else None),
        breakevens=[round(b, 2) for b in breakevens],
        expected_value=0.0,  # finalized in generate.py once sized
        horizon_days=round(horizon_days, 2),
        entry_reason=entry_reason,
        invalidation_condition=invalidation,
        probability_band=([round(band[0], 2), round(band[1], 2)] if band else None),
        liquidity_score=liq_score,
        volatility_risk=_vol_risk(ctx),
        time_stop=round(horizon_days, 2),
        target_exit=target_exit,
        stop_exit=stop_exit,
        exit_rules=exit_rules,
        defined_risk=defined_risk,
        regime_kind=regime_kind,
        tail_loss_per_unit=tail_loss,
        drivers={
            "regime": ctx.regime.label,
            "min_oi": min_oi,
            "worst_spread_pct": worst_spread,
            "atm_iv": ctx.atm_iv,
            "iv_rank": ctx.iv_rank,
            "expected_move": ctx.expected_move,
            **(extra_drivers or {}),
        },
        score_components={"regime_fit": _regime_fit(ctx, regime_kind), "edge_prob": edge_prob},
    )


def _credit_exit_rules(horizon: float) -> dict:
    return {"take_profit_pct": 0.5, "stop_loss_pct": 2.0, "time_exit_days": max(0.0, horizon - 0.5), "regime_flip_exit": True}


def _debit_exit_rules(horizon: float) -> dict:
    return {"take_profit_pct": 1.0, "stop_loss_pct": 0.5, "time_exit_days": max(0.0, horizon - 0.5), "regime_flip_exit": True}


# --- strategies -------------------------------------------------------------
@register("iron_condor")
def iron_condor(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    if ctx.dist is None or not ctx.expected_move:
        return []
    em, step, lot = ctx.expected_move, _step(ctx), ctx.chain.lot_size or 1
    wing = max(2, round(0.4 * em / step)) * step
    sc = ctx.nearest_strike(ctx.spot + em)
    sp = ctx.nearest_strike(ctx.spot - em)
    if sc is None or sp is None:
        return []
    lc, lp = sc + wing, sp - wing
    legs = [
        _opt_leg(ctx, sc, OptionType.CALL, "SELL"),
        _opt_leg(ctx, lc, OptionType.CALL, "BUY"),
        _opt_leg(ctx, sp, OptionType.PUT, "SELL"),
        _opt_leg(ctx, lp, OptionType.PUT, "BUY"),
    ]
    if any(leg is None for leg in legs):
        return []
    credit = -_net_cashflow(legs, lot)
    if credit <= 0:
        return []
    width = max(lc - sc, sp - lp) * lot
    max_loss = width - credit
    if max_loss <= 0:
        return []
    credit_pts = credit / lot
    be_lo, be_hi = sp - credit_pts, sc + credit_pts
    edge = ctx.prob_between_physical(be_lo, be_hi) or 0.0
    cand = _make(
        ctx, strategy="iron_condor", direction=NEUTRAL, legs=legs,
        max_loss_per_unit=max_loss, max_profit_per_unit=credit, breakevens=[be_lo, be_hi],
        edge_prob=edge, regime_kind="short_vol", defined_risk=True,
        entry_reason=f"Positive-gamma/pinning regime; sell the ±1σ wings ({sp:.0f}/{sc:.0f}), defined-risk condor.",
        invalidation=f"Spot breaks outside [{be_lo:.0f}, {be_hi:.0f}] or regime flips to trend-amplifying.",
        exit_rules=_credit_exit_rules(ctx.event.get("days_to_expiry", ctx.T * 365)),
        horizon_days=ctx.event.get("days_to_expiry", ctx.T * 365),
    )
    return [cand] if cand else []


@register("short_strangle")
def short_strangle(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    if not getattr(cfg, "seller_mode", False) or ctx.dist is None or not ctx.expected_move:
        return []
    em, lot = ctx.expected_move, ctx.chain.lot_size or 1
    sc = ctx.nearest_strike(ctx.spot + 1.1 * em)
    sp = ctx.nearest_strike(ctx.spot - 1.1 * em)
    legs = [_opt_leg(ctx, sc, OptionType.CALL, "SELL"), _opt_leg(ctx, sp, OptionType.PUT, "SELL")]
    if any(leg is None for leg in legs):
        return []
    credit = -_net_cashflow(legs, lot)
    if credit <= 0:
        return []
    stop_mult = 2.5  # modeled stop: naked risk capped at 2.5x credit (documented approximation)
    max_loss = stop_mult * credit
    credit_pts = credit / lot
    be_lo, be_hi = sp - credit_pts, sc + credit_pts
    edge = ctx.prob_between_physical(be_lo, be_hi) or 0.0
    cand = _make(
        ctx, strategy="short_strangle", direction=NEUTRAL, legs=legs,
        max_loss_per_unit=max_loss, max_profit_per_unit=credit, breakevens=[be_lo, be_hi],
        edge_prob=edge, regime_kind="short_vol", defined_risk=False,
        entry_reason=f"Seller-mode: naked ±1.1σ strangle ({sp:.0f}/{sc:.0f}) to harvest rich premium; risk capped by a {stop_mult:g}x-credit stop.",
        invalidation=f"Spot approaches a short strike or a {stop_mult:g}x-credit loss; regime flip.",
        exit_rules={"take_profit_pct": 0.5, "stop_loss_pct": stop_mult, "time_exit_days": max(0.0, ctx.event.get("days_to_expiry", ctx.T * 365) - 0.5), "regime_flip_exit": True},
        horizon_days=ctx.event.get("days_to_expiry", ctx.T * 365),
        extra_drivers={"stop_mult": stop_mult, "naked": True},
    )
    return [cand] if cand else []


def _credit_spread(ctx: SignalContext, ot: OptionType, direction: str) -> TradeCandidate | None:
    if ctx.dist is None or not ctx.expected_move:
        return None
    em, step, lot = ctx.expected_move, _step(ctx), ctx.chain.lot_size or 1
    wing = max(2, round(0.5 * em / step)) * step
    if ot == OptionType.PUT:  # bullish put credit spread below spot
        short_k = ctx.nearest_strike(ctx.spot - 0.5 * em)
        long_k = (short_k - wing) if short_k is not None else None
    else:  # bearish call credit spread above spot
        short_k = ctx.nearest_strike(ctx.spot + 0.5 * em)
        long_k = (short_k + wing) if short_k is not None else None
    legs = [_opt_leg(ctx, short_k, ot, "SELL"), _opt_leg(ctx, long_k, ot, "BUY")]
    if any(leg is None for leg in legs):
        return None
    credit = -_net_cashflow(legs, lot)
    if credit <= 0:
        return None
    width = abs(short_k - long_k) * lot
    max_loss = width - credit
    if max_loss <= 0:
        return None
    credit_pts = credit / lot
    if ot == OptionType.PUT:
        be = short_k - credit_pts
        edge = ctx.prob_above_physical(be) or 0.0
        name, reason = "put_credit_spread", f"Bullish bias; sell the {short_k:.0f} put spread above support."
    else:
        be = short_k + credit_pts
        edge = ctx.prob_below_physical(be) or 0.0
        name, reason = "call_credit_spread", f"Bearish bias; sell the {short_k:.0f} call spread below resistance."
    return _make(
        ctx, strategy=name, direction=direction, legs=legs,
        max_loss_per_unit=max_loss, max_profit_per_unit=credit, breakevens=[be],
        edge_prob=edge, regime_kind="short_vol", defined_risk=True,
        entry_reason=reason,
        invalidation=f"Spot crosses breakeven {be:.0f} against the position.",
        exit_rules=_credit_exit_rules(ctx.event.get("days_to_expiry", ctx.T * 365)),
        horizon_days=ctx.event.get("days_to_expiry", ctx.T * 365),
    )


@register("put_credit_spread")
def put_credit_spread(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    # Bullish-leaning only when the market-implied drift / put-wall support agrees.
    pa = ctx.prob_above(ctx.spot)
    if pa is None or pa < 0.50:
        return []
    c = _credit_spread(ctx, OptionType.PUT, BULLISH)
    return [c] if c else []


@register("call_credit_spread")
def call_credit_spread(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    pb = ctx.prob_below(ctx.spot)
    if pb is None or pb < 0.50:
        return []
    c = _credit_spread(ctx, OptionType.CALL, BEARISH)
    return [c] if c else []


@register("long_straddle")
def long_straddle(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    if ctx.dist is None or not ctx.expected_move:
        return []
    lot = ctx.chain.lot_size or 1
    atm = ctx.atm_strike()
    legs = [_opt_leg(ctx, atm, OptionType.CALL, "BUY"), _opt_leg(ctx, atm, OptionType.PUT, "BUY")]
    if any(leg is None for leg in legs):
        return []
    debit = _net_cashflow(legs, lot)
    if debit <= 0:
        return []
    debit_pts = debit / lot
    be_lo, be_hi = atm - debit_pts, atm + debit_pts
    inside = ctx.prob_between_physical(be_lo, be_hi) or 0.0
    edge = 1.0 - inside  # profit requires finishing OUTSIDE the breakevens (physical measure)
    cand = _make(
        ctx, strategy="long_straddle", direction=LONG_VOL, legs=legs,
        max_loss_per_unit=debit, max_profit_per_unit=None, breakevens=[be_lo, be_hi],
        edge_prob=edge, regime_kind="long_vol", defined_risk=True,
        entry_reason=f"Trend-amplifying / cheap IV: buy the {atm:.0f} straddle for a break beyond [{be_lo:.0f}, {be_hi:.0f}].",
        invalidation="IV crush or time decay with spot pinned inside the breakevens.",
        exit_rules=_debit_exit_rules(ctx.event.get("days_to_expiry", ctx.T * 365)),
        horizon_days=ctx.event.get("days_to_expiry", ctx.T * 365),
    )
    return [cand] if cand else []


@register("long_strangle")
def long_strangle(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    if ctx.dist is None or not ctx.expected_move:
        return []
    em, lot = ctx.expected_move, ctx.chain.lot_size or 1
    kc = ctx.nearest_strike(ctx.spot + 0.6 * em)
    kp = ctx.nearest_strike(ctx.spot - 0.6 * em)
    legs = [_opt_leg(ctx, kc, OptionType.CALL, "BUY"), _opt_leg(ctx, kp, OptionType.PUT, "BUY")]
    if any(leg is None for leg in legs):
        return []
    debit = _net_cashflow(legs, lot)
    if debit <= 0:
        return []
    debit_pts = debit / lot
    be_lo, be_hi = kp - debit_pts, kc + debit_pts
    edge = 1.0 - (ctx.prob_between_physical(be_lo, be_hi) or 0.0)
    cand = _make(
        ctx, strategy="long_strangle", direction=LONG_VOL, legs=legs,
        max_loss_per_unit=debit, max_profit_per_unit=None, breakevens=[be_lo, be_hi],
        edge_prob=edge, regime_kind="long_vol", defined_risk=True,
        entry_reason=f"Cheap OTM vol: buy the {kp:.0f}/{kc:.0f} strangle for a large move.",
        invalidation="IV crush / pinning inside the breakevens.",
        exit_rules=_debit_exit_rules(ctx.event.get("days_to_expiry", ctx.T * 365)),
        horizon_days=ctx.event.get("days_to_expiry", ctx.T * 365),
    )
    return [cand] if cand else []


@register("iv_crush_fade")
def iv_crush_fade(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    if ctx.crush.get("crush_score", 0) < SETTINGS.iv_crush_threshold:
        return []
    cands = iron_condor(ctx, cfg)  # reuse the defined-risk condor
    for c in cands:
        c.strategy = "iv_crush_fade"
        c.direction = SHORT_VOL
        c.entry_reason = f"IV-crush score {ctx.crush.get('crush_score')}: fade rich premium with a defined-risk condor into the drop."
        c.drivers["crush_score"] = ctx.crush.get("crush_score")
        c.score_components["regime_fit"] = max(c.score_components.get("regime_fit", 0.5), 0.8)
    return cands


@register("directional_future")
def directional_future(ctx: SignalContext, cfg) -> list[TradeCandidate]:
    if ctx.dist is None or not ctx.expected_move:
        return []
    pa = ctx.prob_above(ctx.spot)
    if pa is None:
        return []
    lot = ctx.chain.lot_size or 1
    entry = float(ctx.chain.future_price or ctx.forward or ctx.spot)
    em = ctx.expected_move
    if pa >= 0.54:
        side, direction, edge = "BUY", BULLISH, pa
    elif pa <= 0.46:
        side, direction, edge = "SELL", BEARISH, (ctx.prob_below(ctx.spot) or 0.0)
    else:
        return []
    stop_pts = 0.6 * em
    target_pts = 1.2 * em
    max_loss = stop_pts * lot
    max_profit = target_pts * lot
    leg = Leg(
        side=side, lots=1, expiry=ctx.expiry, ref_price=entry,
        option_type=None, strike=None, instrument_type="FUT",
        delta=1.0 if side == "BUY" else -1.0,
        symbol=f"{ctx.underlying}{ctx.expiry.replace('-', '')}FUT",
    )
    horizon = min(5.0, ctx.event.get("days_to_expiry", 5.0))
    cand = _make(
        ctx, strategy="directional_future", direction=direction, legs=[leg],
        max_loss_per_unit=max_loss, max_profit_per_unit=max_profit, breakevens=[entry],
        edge_prob=edge, regime_kind="trend", defined_risk=True,
        entry_reason=f"Market-implied drift {direction}; take the future with a {stop_pts:.0f}-pt stop / {target_pts:.0f}-pt target.",
        invalidation=f"Spot moves {stop_pts:.0f} pts against entry {entry:.0f}.",
        exit_rules={"take_profit_pct": 1.0, "stop_loss_pct": 1.0, "time_exit_days": horizon, "regime_flip_exit": True,
                    "target_level": (entry + target_pts) if side == "BUY" else (entry - target_pts),
                    "stop_level": (entry - stop_pts) if side == "BUY" else (entry + stop_pts)},
        horizon_days=horizon,
        extra_drivers={"entry": entry, "stop_pts": stop_pts, "target_pts": target_pts},
    )
    return [cand] if cand else []
