"""Gamma Exposure (GEX) and the zero-gamma flip — the dealer-positioning regime read.

Modeling choices made explicit (vendors disagree, so we state ours):

1. **Sign convention** = ``dealers long calls / short puts`` (the dominant SpotGamma
   convention): call gamma contributes POSITIVE GEX, put gamma contributes NEGATIVE.
   Flip with ``dealer_sign`` if you prefer the opposite assumption.
2. **Gamma** is the Black-76 gamma w.r.t. the FORWARD (the index and its future move
   together intraday, so dealer hedging in the underlying is captured).
3. **Scaling** = spot-SQUARED: per-strike GEX is ``gamma · OI · lot · spot² · 0.01``,
   i.e. ₹ change in aggregate dealer delta per 1% move in the index.

Above the zero-gamma flip dealers are net long gamma → hedge against moves → mean-reverting /
pinned / lower vol. Below it, net short gamma → hedge with moves → trend-amplifying.

Validate sign and level on real NSE data before trusting in production.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from . import greeks as gk
from .forward import resolve_forward
from .util import year_fraction


@dataclass
class GEXResult:
    total_gex: float
    per_strike: dict[float, float]
    call_walls: list[tuple[float, float]]
    put_walls: list[tuple[float, float]]
    zero_gamma_flip: float | None
    spot: float
    forward: float
    forward_source: str
    extra: dict = field(default_factory=dict)


def _row_iv(row, F, strike, T, r) -> float | None:
    if row.iv is not None and row.iv > 0:
        return row.iv
    if row.ltp is not None and row.ltp > 0:
        iv = gk.implied_vol(row.ltp, row.option_type, F, strike, T, r)
        return iv if iv == iv else None  # filter NaN
    return None


def compute_gex(
    chain: OptionChain,
    r: float | None = None,
    q: float | None = None,
    dealer_sign: int = 1,
    n_walls: int = 3,
) -> GEXResult:
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
    spot = chain.spot
    F, F_src = resolve_forward(chain, r, q)
    basis = F - spot
    lot = chain.lot_size or 1
    scale = spot**2 * 0.01 * lot

    per_strike: dict[float, float] = {}
    iv_by_strike_type: dict[tuple[float, str], float] = {}

    for row in chain.rows:
        iv = _row_iv(row, F, row.strike, T, r)
        if iv is None:
            continue
        iv_by_strike_type[(row.strike, row.option_type.value)] = iv
        g = float(gk.gamma(F, row.strike, T, r, iv))
        contribution = g * row.oi * scale
        signed = (+contribution if row.option_type == OptionType.CALL else -contribution) * dealer_sign
        per_strike[row.strike] = per_strike.get(row.strike, 0.0) + signed

    total = float(sum(per_strike.values()))
    pos = sorted(((k, v) for k, v in per_strike.items() if v > 0), key=lambda x: x[1], reverse=True)
    neg = sorted(((k, v) for k, v in per_strike.items() if v < 0), key=lambda x: x[1])

    flip = _zero_gamma_flip(chain, iv_by_strike_type, T, r, dealer_sign, basis)

    return GEXResult(
        total_gex=total,
        per_strike=per_strike,
        call_walls=pos[:n_walls],
        put_walls=neg[:n_walls],
        zero_gamma_flip=flip,
        spot=spot,
        forward=F,
        forward_source=F_src,
    )


def _net_gex_at(spot_hyp, chain, iv_map, T, r, dealer_sign, basis) -> float:
    """Net GEX if the index were at ``spot_hyp`` (forward shifts by the same basis; IV fixed)."""
    F_hyp = spot_hyp + basis
    scale = spot_hyp**2 * 0.01 * (chain.lot_size or 1)
    total = 0.0
    for row in chain.rows:
        iv = iv_map.get((row.strike, row.option_type.value))
        if iv is None:
            continue
        g = float(gk.gamma(F_hyp, row.strike, T, r, iv))
        c = g * row.oi * scale
        total += (+c if row.option_type == OptionType.CALL else -c) * dealer_sign
    return total


def _zero_gamma_flip(chain, iv_map, T, r, dealer_sign, basis, span=0.12, steps=240):
    """Find the spot where net GEX crosses zero, scanning ±span around spot."""
    spot = chain.spot
    grid = np.linspace(spot * (1 - span), spot * (1 + span), steps)
    vals = np.array([_net_gex_at(s, chain, iv_map, T, r, dealer_sign, basis) for s in grid])
    sign = np.sign(vals)
    crossings = np.where(np.diff(sign) != 0)[0]
    if len(crossings) == 0:
        return None
    idx = min(crossings, key=lambda i: abs(grid[i] - spot))
    x0, x1 = grid[idx], grid[idx + 1]
    y0, y1 = vals[idx], vals[idx + 1]
    if y1 == y0:
        return float((x0 + x1) / 2)
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))
