"""Anvil Live v2 — option-structure builder (pure stdlib).

Faithful port of anvil/anvil/strategy/library.py. Given a MarketState (live chain + analytics),
build real, priced, defined-risk (and modeled-stop naked) option structures and score each by:

  * net credit/debit      — from REAL chain fills (sell hits the bid, buy lifts the ask)
  * max_loss per lot       — exact for defined-risk; STRESS-based (3σ gap) for naked (adversary #3/#11)
  * max_profit per lot
  * breakevens
  * edge_prob (POP)        — PHYSICAL-measure prob of finishing profitable (the VRP edge)
  * ev_gross / ev_net      — expected ₹ P&L per lot, integrated over the physical terminal grid,
                             net of the full India F&O cost stack (adversary #8)
  * regime_kind            — short_vol | long_vol | trend (for the regime gate)

Every number is MODEL P&L off a frozen snapshot, not a guaranteed fill (adversary #7). Read-only.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import config
import costs_v2
from engine_v2 import MarketState


@dataclass
class Structure:
    strategy: str
    underlying: str
    asset_class: str
    direction: str            # NEUTRAL | BULLISH | BEARISH | LONG_VOL | SHORT_VOL
    regime_kind: str          # short_vol | long_vol | trend
    defined_risk: bool
    legs: list                # [{side, option_type, strike, entry_fill, mid, bid, ask, oi}]
    lot_size: int
    net_credit: float         # per lot, ₹ (positive = credit received)
    max_loss: float           # per lot, ₹ (modeled; stress-based if naked)
    max_profit: float | None  # per lot, ₹
    breakevens: list
    edge_prob: float          # physical-measure POP (RAW — never calibrated into the gate)
    ev_gross: float           # per lot, ₹, physical-measure
    ev_net: float             # per lot, ₹, after round-trip costs
    cost_round_trip: float    # per lot, ₹
    ev_on_risk: float         # ev_net / max_loss
    liquidity: float          # 0..1
    min_oi: float
    worst_spread_pct: float | None
    rationale: str
    drivers: dict = field(default_factory=dict)


# --- payoff machinery -------------------------------------------------------
def _intrinsic(option_type: str, strike: float, s_t: float) -> float:
    if option_type == "CE":
        return max(s_t - strike, 0.0)
    return max(strike - s_t, 0.0)


def _entry_fill(side: str, leg) -> float:
    return costs_v2.fill_price(side, leg.mid, leg.bid, leg.ask)


def _pnl_per_lot(legs_priced: list, lot: int, s_t: float) -> float:
    """P&L per lot at terminal spot s_t. SELL: +fill-intrinsic; BUY: intrinsic-fill (per share)."""
    pnl = 0.0
    for lg in legs_priced:
        intr = _intrinsic(lg["option_type"], lg["strike"], s_t)
        per_share = (lg["entry_fill"] - intr) if lg["side"] == "SELL" else (intr - lg["entry_fill"])
        pnl += per_share
    return pnl * lot


def _grid_ev_pop(ms: MarketState, legs_priced: list) -> tuple[float, float]:
    """Integrate per-lot P&L over the PHYSICAL terminal distribution → (ev_gross_per_lot, pop)."""
    grid = ms.physical_grid()
    ev = 0.0
    pop = 0.0
    for s_t, mass in grid:
        p = _pnl_per_lot(legs_priced, ms.lot_size, s_t)
        ev += mass * p
        if p > 0:
            pop += mass
    return ev, pop


def _liquidity(legs_priced: list) -> tuple[float, float, float | None]:
    ois, spreads = [], []
    for lg in legs_priced:
        ois.append(lg["oi"])
        if lg["bid"] and lg["ask"] and lg["bid"] > 0 and lg["ask"] > 0:
            mid = (lg["bid"] + lg["ask"]) / 2.0
            if mid > 0:
                spreads.append((lg["ask"] - lg["bid"]) / mid)
    min_oi = min(ois) if ois else 0.0
    worst = max(spreads) if spreads else None
    oi_score = min(1.0, min_oi / 100_000.0)
    spread_score = 1.0 if worst is None else max(0.0, 1.0 - worst / 0.10)
    return round(0.6 * oi_score + 0.4 * spread_score, 3), min_oi, worst


def _price_legs(ms: MarketState, raw_legs: list) -> list | None:
    """raw_legs = [(side, option_type, strike)]; resolve mids/fills off the chain. None if any missing."""
    out = []
    for side, ot, strike in raw_legs:
        leg = ms.leg(strike, ot)
        if leg is None:
            return None
        out.append({"side": side, "option_type": ot, "strike": float(strike),
                    "mid": leg.mid, "bid": leg.bid, "ask": leg.ask, "oi": leg.oi,
                    "entry_fill": _entry_fill(side, leg)})
    return out


def _stress_max_loss(ms: MarketState, legs_priced: list, n_sigma: float = 3.0) -> float:
    """Worst per-lot loss across a ±n_sigma IMPLIED gap — honest sizing for naked structures."""
    s = ms.atm_iv * math.sqrt(max(ms.T, 1e-6))
    lo = ms.spot * math.exp(-n_sigma * s)
    hi = ms.spot * math.exp(+n_sigma * s)
    worst = min(_pnl_per_lot(legs_priced, ms.lot_size, lo),
                _pnl_per_lot(legs_priced, ms.lot_size, hi))
    return abs(min(worst, 0.0)) or 1.0


def _finalize(ms: MarketState, *, strategy, direction, regime_kind, defined_risk,
              legs_priced, max_loss, max_profit, breakevens, rationale, drivers) -> Structure | None:
    if not legs_priced or max_loss <= 0:
        return None
    net_credit = sum((lg["entry_fill"] if lg["side"] == "SELL" else -lg["entry_fill"]) for lg in legs_priced) * ms.lot_size
    ev_gross, pop = _grid_ev_pop(ms, legs_priced)
    cost = costs_v2.round_trip_cost(legs_priced, ms.lot_size, 1)["total"]
    ev_net = ev_gross - cost
    liq, min_oi, worst = _liquidity(legs_priced)
    return Structure(
        strategy=strategy, underlying=ms.underlying, asset_class=ms.asset_class, direction=direction,
        regime_kind=regime_kind, defined_risk=defined_risk,
        legs=[{"side": lg["side"], "option_type": lg["option_type"], "strike": lg["strike"],
               "entry_fill": round(lg["entry_fill"], 2), "mid": round(lg["mid"], 2),
               "bid": lg["bid"], "ask": lg["ask"], "oi": lg["oi"]} for lg in legs_priced],
        lot_size=ms.lot_size, net_credit=round(net_credit, 2), max_loss=round(max_loss, 2),
        max_profit=(round(max_profit, 2) if max_profit is not None else None),
        breakevens=[round(b, 2) for b in breakevens], edge_prob=round(pop, 4),
        ev_gross=round(ev_gross, 2), ev_net=round(ev_net, 2), cost_round_trip=round(cost, 2),
        ev_on_risk=round(ev_net / max_loss, 4) if max_loss > 0 else 0.0,
        liquidity=liq, min_oi=min_oi, worst_spread_pct=(round(worst, 4) if worst is not None else None),
        rationale=rationale, drivers=drivers)


def _step(ms: MarketState) -> float:
    gaps = [b - a for a, b in zip(ms.strikes, ms.strikes[1:]) if b > a]
    return float(min(gaps)) if gaps else 50.0


# --- the structures ---------------------------------------------------------
def iron_condor(ms: MarketState) -> Structure | None:
    em, step = ms.expected_move, _step(ms)
    if em <= 0:
        return None
    wing = max(2, round(0.4 * em / step)) * step
    sc, sp = ms.nearest_strike(ms.spot + em), ms.nearest_strike(ms.spot - em)
    if sc is None or sp is None:
        return None
    legs = _price_legs(ms, [("SELL", "CE", sc), ("BUY", "CE", sc + wing),
                            ("SELL", "PE", sp), ("BUY", "PE", sp - wing)])
    if legs is None:
        return None
    credit = sum((lg["entry_fill"] if lg["side"] == "SELL" else -lg["entry_fill"]) for lg in legs)
    if credit <= 0:
        return None
    width = max(wing, wing)
    max_loss = (width - credit) * ms.lot_size
    if max_loss <= 0:
        return None
    credit_pts = credit
    be_lo, be_hi = sp - credit_pts, sc + credit_pts
    return _finalize(ms, strategy="iron_condor", direction="NEUTRAL", regime_kind="short_vol",
                     defined_risk=True, legs_priced=legs, max_loss=max_loss,
                     max_profit=credit * ms.lot_size, breakevens=[be_lo, be_hi],
                     rationale=f"Pinning/rich-IV regime: sell the ±1σ wings ({sp:.0f}/{sc:.0f}) as a defined-risk condor; harvest premium while spot stays in [{be_lo:.0f},{be_hi:.0f}].",
                     drivers={"short_strikes": [sp, sc], "wing": wing})


def short_strangle(ms: MarketState) -> Structure | None:
    em = ms.expected_move
    if em <= 0:
        return None
    sc, sp = ms.nearest_strike(ms.spot + 1.1 * em), ms.nearest_strike(ms.spot - 1.1 * em)
    legs = _price_legs(ms, [("SELL", "CE", sc), ("SELL", "PE", sp)])
    if legs is None:
        return None
    credit = sum(lg["entry_fill"] for lg in legs)
    if credit <= 0:
        return None
    max_loss = _stress_max_loss(ms, legs, n_sigma=3.0)   # naked → STRESS sizing, not 2.5×credit
    be_lo, be_hi = sp - credit, sc + credit
    return _finalize(ms, strategy="short_strangle", direction="NEUTRAL", regime_kind="short_vol",
                     defined_risk=False, legs_priced=legs, max_loss=max_loss,
                     max_profit=credit * ms.lot_size, breakevens=[be_lo, be_hi],
                     rationale=f"Seller-mode (NAKED, tail-risk): ±1.1σ strangle {sp:.0f}/{sc:.0f}; max-loss is a 3σ-gap STRESS estimate, not the benign credit.",
                     drivers={"short_strikes": [sp, sc], "naked": True, "stress_sigma": 3.0})


def _credit_spread(ms: MarketState, ot: str, direction: str) -> Structure | None:
    em, step = ms.expected_move, _step(ms)
    if em <= 0:
        return None
    wing = max(2, round(0.5 * em / step)) * step
    if ot == "PE":
        short_k = ms.nearest_strike(ms.spot - 0.5 * em)
        long_k = (short_k - wing) if short_k is not None else None
    else:
        short_k = ms.nearest_strike(ms.spot + 0.5 * em)
        long_k = (short_k + wing) if short_k is not None else None
    if short_k is None or long_k is None:
        return None
    legs = _price_legs(ms, [("SELL", ot, short_k), ("BUY", ot, long_k)])
    if legs is None:
        return None
    credit = sum((lg["entry_fill"] if lg["side"] == "SELL" else -lg["entry_fill"]) for lg in legs)
    if credit <= 0:
        return None
    max_loss = (abs(short_k - long_k) - credit) * ms.lot_size
    if max_loss <= 0:
        return None
    be = (short_k - credit) if ot == "PE" else (short_k + credit)
    name = "put_credit_spread" if ot == "PE" else "call_credit_spread"
    reason = (f"Bullish lean + support: sell the {short_k:.0f} put spread (be {be:.0f})." if ot == "PE"
              else f"Bearish lean + resistance: sell the {short_k:.0f} call spread (be {be:.0f}).")
    return _finalize(ms, strategy=name, direction=direction, regime_kind="short_vol",
                     defined_risk=True, legs_priced=legs, max_loss=max_loss,
                     max_profit=credit * ms.lot_size, breakevens=[be], rationale=reason,
                     drivers={"short_strike": short_k, "long_strike": long_k})


def put_credit_spread(ms: MarketState) -> Structure | None:
    if ms.prob_above_phys(ms.spot) < 0.50:
        return None
    return _credit_spread(ms, "PE", "BULLISH")


def call_credit_spread(ms: MarketState) -> Structure | None:
    if ms.prob_below_phys(ms.spot) < 0.50:
        return None
    return _credit_spread(ms, "CE", "BEARISH")


def long_straddle(ms: MarketState) -> Structure | None:
    atm = ms.atm_strike
    legs = _price_legs(ms, [("BUY", "CE", atm), ("BUY", "PE", atm)])
    if legs is None:
        return None
    debit = sum(lg["entry_fill"] for lg in legs)
    if debit <= 0:
        return None
    be_lo, be_hi = atm - debit, atm + debit
    return _finalize(ms, strategy="long_straddle", direction="LONG_VOL", regime_kind="long_vol",
                     defined_risk=True, legs_priced=legs, max_loss=debit * ms.lot_size,
                     max_profit=None, breakevens=[be_lo, be_hi],
                     rationale=f"Cheap IV / trend-amplify: buy the {atm:.0f} straddle for a break beyond [{be_lo:.0f},{be_hi:.0f}].",
                     drivers={"atm": atm})


def long_strangle(ms: MarketState) -> Structure | None:
    em = ms.expected_move
    if em <= 0:
        return None
    kc, kp = ms.nearest_strike(ms.spot + 0.6 * em), ms.nearest_strike(ms.spot - 0.6 * em)
    legs = _price_legs(ms, [("BUY", "CE", kc), ("BUY", "PE", kp)])
    if legs is None:
        return None
    debit = sum(lg["entry_fill"] for lg in legs)
    if debit <= 0:
        return None
    be_lo, be_hi = kp - debit, kc + debit
    return _finalize(ms, strategy="long_strangle", direction="LONG_VOL", regime_kind="long_vol",
                     defined_risk=True, legs_priced=legs, max_loss=debit * ms.lot_size,
                     max_profit=None, breakevens=[be_lo, be_hi],
                     rationale=f"Cheap OTM vol: buy the {kp:.0f}/{kc:.0f} strangle for a large move.",
                     drivers={"strikes": [kp, kc]})


def directional_debit_spread(ms: MarketState) -> Structure | None:
    """Defined-risk directional (vertical debit) when the tape genuinely trends — replaces naked
    futures so risk stays bounded and the SEBI 'directional call' surface is smaller."""
    em, step = ms.expected_move, _step(ms)
    if em <= 0 or abs(ms.trend_z) < 1.0:
        return None
    wing = max(2, round(1.0 * em / step)) * step
    if ms.trend_z > 0:   # bull call spread
        k_long, k_short, ot, direction = ms.atm_strike, ms.atm_strike + wing, "CE", "BULLISH"
    else:                # bear put spread
        k_long, k_short, ot, direction = ms.atm_strike, ms.atm_strike - wing, "PE", "BEARISH"
    legs = _price_legs(ms, [("BUY", ot, k_long), ("SELL", ot, k_short)])
    if legs is None:
        return None
    debit = sum((-lg["entry_fill"] if lg["side"] == "BUY" else lg["entry_fill"]) for lg in legs)
    debit = -debit  # debit positive = paid
    if debit <= 0:
        return None
    max_loss = debit * ms.lot_size
    max_profit = (abs(k_short - k_long) - debit) * ms.lot_size
    be = (k_long + debit) if ot == "CE" else (k_long - debit)
    return _finalize(ms, strategy="directional_debit_spread", direction=direction, regime_kind="trend",
                     defined_risk=True, legs_priced=legs, max_loss=max_loss, max_profit=max_profit,
                     breakevens=[be],
                     rationale=f"Trend regime (trend_z={ms.trend_z:+.2f}): defined-risk {direction} vertical {k_long:.0f}/{k_short:.0f}, be {be:.0f}.",
                     drivers={"trend_z": round(ms.trend_z, 3)})


ALL_STRUCTURES = [iron_condor, short_strangle, put_credit_spread, call_credit_spread,
                  long_straddle, long_strangle, directional_debit_spread]


def build_candidates(ms: MarketState) -> list[Structure]:
    out = []
    for fn in ALL_STRUCTURES:
        try:
            s = fn(ms)
            if s is not None:
                out.append(s)
        except Exception:
            continue
    return out
