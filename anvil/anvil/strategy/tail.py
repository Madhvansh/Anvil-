"""True-tail risk for sizing — replace stop-multiple risk with a CVaR/stress tail.

A premium-seller's real risk is the GAP through the stop, not the stop itself; a flat 5% equity stop
also hides that a high-vol name is riskier than a quiet one at the same price. These pure helpers give
a finite, honest per-unit tail used to SIZE against the gap (via the sizing CVaR cap) without
corrupting the candidate's modeled max-loss / EV:

  * naked option structures -> the stress loss at a ``stress_z``-sigma terminal move (settlement
    intrinsic of the breached legs net of credit) — the v2 "3-sigma stress max-loss" doctrine;
  * linear equity legs       -> a z-sigma move scaled by trailing realized vol, floored at a flat %
    so a quiet name never sizes absurdly large (here the stop IS the exit, so this becomes max_loss).

Pure functions, no I/O, numpy-free.
"""

from __future__ import annotations

import math

from ..models import OptionType


def realized_daily_vol(closes: list[float]) -> float | None:
    """Trailing realized DAILY vol (fraction) from a close series; None if too short."""
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1]]
    if len(rets) < 2:
        return None
    m = sum(rets) / len(rets)
    var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)


def equity_tail_max_loss(
    price: float,
    lot: int,
    *,
    sigma_daily: float | None,
    horizon_days: float,
    tail_z: float = 2.06,
    floor_pct: float = 0.05,
) -> float:
    """Per-unit max-loss for a linear equity leg: ``max(floor, z·sigma·sqrt(h)·price)·lot``.

    ``sigma_daily`` is trailing realized daily vol (fraction); when unknown only the floor applies.
    ``tail_z`` ≈ the Normal CVaR-95 multiplier; ``floor_pct`` keeps the old flat stop as a lower bound.
    This becomes the equity tip's ``max_loss`` (the stop is the real exit, so EV stays consistent)."""
    lot = int(lot or 1)
    floor = floor_pct * float(price) * lot
    if not sigma_daily or sigma_daily <= 0 or horizon_days <= 0:
        return round(floor, 2)
    vol_tail = tail_z * float(sigma_daily) * math.sqrt(float(horizon_days)) * float(price) * lot
    return round(max(floor, vol_tail), 2)


def _terminal_settlement_pnl(legs, lot_size: int, terminal_spot: float) -> float:
    """Per-unit settlement P&L of an option/linear structure at ``terminal_spot`` (intrinsic).

    Accepts ``Leg`` objects (``side``/``option_type``/``strike``/``ref_price``/``instrument_type``).
    Mirrors the v2 tracker's settlement math so the stress tail matches how a trade actually resolves.
    """
    pnl = 0.0
    for leg in legs:
        side = str(getattr(leg, "side", "")).upper()
        sign = 1 if side == "SELL" else -1  # short collects premium, pays intrinsic; long the reverse
        entry = float(getattr(leg, "ref_price", 0.0) or 0.0)
        ot = getattr(leg, "option_type", None)
        if ot is None:  # linear EQ/FUT leg
            # long gains (S - entry), short gains (entry - S)
            pnl += (-sign) * (terminal_spot - entry)
            continue
        k = float(getattr(leg, "strike", 0.0) or 0.0)
        intrinsic = max(terminal_spot - k, 0.0) if ot == OptionType.CALL else max(k - terminal_spot, 0.0)
        # SELL: keep premium, owe intrinsic -> (entry - intrinsic); BUY: (intrinsic - entry)
        pnl += (entry - intrinsic) if side == "SELL" else (intrinsic - entry)
    return pnl * int(lot_size or 1)


def naked_stress_max_loss(
    legs,
    lot_size: int,
    spot: float,
    one_sigma_move: float,
    *,
    stress_z: float = 3.0,
) -> float | None:
    """Per-unit stress loss (positive ₹) of a naked structure at ±``stress_z``-sigma terminal moves.

    ``one_sigma_move`` is the ±1σ index move (``ctx.expected_move``). Returns the worse of the up/down
    stressed settlement losses, or None if it can't be computed (no move). For a short strangle this is
    the gap loss when a short strike is breached — far worse than a stop-multiple, which is the point."""
    if not one_sigma_move or one_sigma_move <= 0 or spot <= 0:
        return None
    shock = stress_z * float(one_sigma_move)
    up_loss = -_terminal_settlement_pnl(legs, lot_size, spot + shock)
    down_loss = -_terminal_settlement_pnl(legs, lot_size, spot - shock)
    worst = max(up_loss, down_loss, 0.0)
    return round(worst, 2)
