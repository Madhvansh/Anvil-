"""Per-ticket risk distribution — the honest spread shown instead of a point-₹ number.

Three pure pieces:
  * ``legs_to_positions`` projects a tip's serialized legs onto ``engine.montecarlo.mc_pnl``'s
    ``Position`` inputs, so every actionable tip can carry an mc_pnl risk map (percentiles, VaR/CVaR)
    — the market-implied (RISK-NEUTRAL) tail, a conservative RISK map, NOT a return forecast.
  * ``ruin_and_drawdown`` runs a small Monte-Carlo over repeated SIZED bets using a per-trade
    return-on-equity distribution → risk-of-ruin + the forward max-drawdown distribution. Needs no
    chain, so equity tips get it too.
  * ``modeled_returns`` builds a 2-point (win/loss) return sample when no measured history exists.

These are OWNER-only artifacts (position-level sized risk); the public surface never shows them.
"""

from __future__ import annotations

import numpy as np

from ..models import OptionType, Position


def legs_to_positions(legs, lot_size, underlying, chain=None):
    """Project serialized tip legs onto mc_pnl ``Position`` objects (signed quantity, iv from chain)."""
    positions: list[Position] = []
    for leg in legs:
        side = str(leg.get("side", "")).upper()
        lots = int(leg.get("lots", 0) or 0)
        if lots <= 0:
            continue
        sign = 1 if side == "BUY" else -1
        qty = float(sign * lots * int(lot_size or 1))  # F&O quantity already * lot size (model convention)
        strike = leg.get("strike")
        ot_raw = leg.get("option_type")
        option_type = None
        iv = None
        if ot_raw:
            try:
                option_type = OptionType(ot_raw)
            except ValueError:
                option_type = None
            if chain is not None and strike is not None and option_type is not None:
                row = chain.row(float(strike), option_type)
                iv = row.iv if row else None
        ref = float(leg.get("ref_price", 0.0) or 0.0)
        positions.append(
            Position(
                symbol=leg.get("symbol") or str(underlying),
                underlying=str(underlying),
                instrument_type=leg.get("instrument_type", "CE"),
                quantity=qty,
                lot_size=int(lot_size or 1),
                avg_price=ref,
                ltp=ref,
                strike=float(strike) if strike is not None else None,
                option_type=option_type,
                expiry=leg.get("expiry"),
                iv=iv,
                beta=1.0,
            )
        )
    return positions


def modeled_returns(p_win: float, win_ret: float, loss_ret: float, n: int = 200) -> list[float]:
    """A 2-point return-on-equity sample for a Bernoulli bet (``win_ret`` > 0 > ``loss_ret``)."""
    p = min(1.0, max(0.0, float(p_win)))
    k = int(round(p * n))
    return [float(win_ret)] * k + [float(loss_ret)] * (n - k)


def ruin_and_drawdown(
    per_trade_returns,
    *,
    n_bets: int = 50,
    n_sims: int = 5000,
    ruin_threshold: float = 0.5,
    seed: int = 0,
    basis: str = "modeled",
) -> dict | None:
    """MC over ``n_bets`` repeated SIZED bets drawn from ``per_trade_returns`` (return-on-equity).

    Returns ``risk_of_ruin`` = P(equity ever falls to ``ruin_threshold``× start) and the forward
    max-drawdown distribution {p50, p95, max}. ``basis`` tags whether the inputs were measured or
    modeled. Deterministic under ``seed``. None if there are no usable returns."""
    arr = np.asarray([r for r in per_trade_returns if r is not None], dtype=float)
    if arr.size == 0:
        return None
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(arr, size=(int(n_sims), int(n_bets)), replace=True)
    equity_paths = np.cumprod(1.0 + draws, axis=1)
    running_peak = np.maximum.accumulate(equity_paths, axis=1)
    drawdowns = 1.0 - equity_paths / running_peak
    max_dd = drawdowns.max(axis=1)
    ruined = equity_paths.min(axis=1) <= float(ruin_threshold)
    return {
        "risk_of_ruin": round(float(ruined.mean()), 4),
        "forward_drawdown": {
            "p50": round(float(np.percentile(max_dd, 50)), 4),
            "p95": round(float(np.percentile(max_dd, 95)), 4),
            "max": round(float(max_dd.max()), 4),
        },
        "n_bets": int(n_bets),
        "ruin_threshold": float(ruin_threshold),
        "basis": basis,
    }
