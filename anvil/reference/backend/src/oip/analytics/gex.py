"""Gamma Exposure (GEX) and the zero-gamma flip — a dealer-positioning regime read.

Computed on the Black-76 gamma (futures price), unlike spot-based US tooling.

Modeling choices made explicit (vendors disagree):
- **Sign convention** = dealers long calls / short puts: call gamma adds POSITIVE GEX, put gamma
  NEGATIVE. Flip with `dealer_sign=-1` for the opposite assumption.
- **Scaling** = future-SQUARED: per-strike GEX = gamma * OI * lot_size * F**2 * 0.01.

Above the zero-gamma flip, dealers are net long gamma → hedge against moves → mean-reverting/pinned.
Below it, net short gamma → hedge with moves → trend-amplifying.

⚠️ NEEDS LIVE NSE VALIDATION. The sign/level conventions come from US equity markets; Indian
microstructure (weekly expiries, STT, participant mix) differs. Until validated against NSE history
in the backtest lab, treat GEX levels/flip as a HYPOTHESIS, not a calibrated signal.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..config import lot_size
from ..domain.enums import OptionType
from ..domain.models import OptionChain
from ..quant import black76
from .util import chain_t_years, effective_iv


@dataclass
class GEXResult:
    total_gex: float
    per_strike: dict[float, float]
    call_walls: list[tuple[float, float]]  # largest positive GEX strikes (resistance)
    put_walls: list[tuple[float, float]]  # most negative GEX strikes (support)
    zero_gamma_flip: float | None
    future_price: float
    needs_nse_validation: bool = True
    extra: dict = field(default_factory=dict)


def _iv_map(chain: OptionChain, F: float, t: float, r: float) -> dict[tuple[float, OptionType], float]:
    m: dict[tuple[float, OptionType], float] = {}
    for row in chain.rows:
        for q in (row.call, row.put):
            if q is None:
                continue
            iv = effective_iv(q, F, row.strike, t, r)
            if iv is not None:
                m[(row.strike, q.option_type)] = iv
    return m


def _net_gex_at(F_hyp: float, chain, iv_map, t, r, lot, dealer_sign) -> float:
    scale = F_hyp * F_hyp * 0.01 * lot
    total = 0.0
    for row in chain.rows:
        for q in (row.call, row.put):
            if q is None or not q.oi:
                continue
            iv = iv_map.get((row.strike, q.option_type))
            if iv is None:
                continue
            g = float(black76.gamma(F_hyp, row.strike, t, r, iv))
            contribution = g * q.oi * scale
            total += (contribution if q.option_type == OptionType.CALL else -contribution) * dealer_sign
    return total


def _zero_gamma_flip(chain, iv_map, t, r, lot, dealer_sign, span=0.12, steps=240) -> float | None:
    F = chain.future_price
    grid = np.linspace(F * (1 - span), F * (1 + span), steps)
    vals = np.array([_net_gex_at(x, chain, iv_map, t, r, lot, dealer_sign) for x in grid])
    crossings = np.where(np.diff(np.sign(vals)) != 0)[0]
    if len(crossings) == 0:
        return None
    i = min(crossings, key=lambda j: abs(grid[j] - F))  # nearest crossing to spot/future
    x0, x1, y0, y1 = grid[i], grid[i + 1], vals[i], vals[i + 1]
    if y1 == y0:
        return float((x0 + x1) / 2)
    return float(x0 - y0 * (x1 - x0) / (y1 - y0))  # linear interpolation to zero


def compute_gex(chain: OptionChain, dealer_sign: int = 1, n_walls: int = 3) -> GEXResult:
    F, r = chain.future_price, chain.risk_free_rate
    t = max(chain_t_years(chain), 1e-6)
    lot = lot_size(chain.underlying)
    scale = F * F * 0.01 * lot
    iv_map = _iv_map(chain, F, t, r)

    per_strike: dict[float, float] = {}
    for row in chain.rows:
        for q in (row.call, row.put):
            if q is None or not q.oi:
                continue
            iv = iv_map.get((row.strike, q.option_type))
            if iv is None:
                continue
            g = float(black76.gamma(F, row.strike, t, r, iv))
            contribution = g * q.oi * scale
            signed = (contribution if q.option_type == OptionType.CALL else -contribution) * dealer_sign
            per_strike[row.strike] = per_strike.get(row.strike, 0.0) + signed

    total = float(sum(per_strike.values()))
    pos = sorted(((k, v) for k, v in per_strike.items() if v > 0), key=lambda x: x[1], reverse=True)
    neg = sorted(((k, v) for k, v in per_strike.items() if v < 0), key=lambda x: x[1])
    flip = _zero_gamma_flip(chain, iv_map, t, r, lot, dealer_sign)

    return GEXResult(
        total_gex=total,
        per_strike=per_strike,
        call_walls=pos[:n_walls],
        put_walls=neg[:n_walls],
        zero_gamma_flip=flip,
        future_price=F,
    )
