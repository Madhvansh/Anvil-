"""Market-implied (risk-neutral) distribution.

Two expected-move readings, plus a Breeden-Litzenberger risk-neutral density (RND):

- `em_atm_iv`   : the 1σ lognormal move, F·σ_atm·√t (index points).
- `em_straddle` : the ATM straddle price — the market's quoted "expected move" proxy.
- RND          : f(K) = e^{rt} · ∂²C/∂K², estimated by a non-uniform second difference of Black-76
  model call prices across strikes, clipped to ≥0 and normalized to integrate to 1.

These are RISK-NEUTRAL (market-implied) probabilities, NOT real-world / calibrated ones — a
distinction the calibration ledger exists to make. Labelled as such on every surface.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..domain.enums import OptionType
from ..domain.models import OptionChain
from ..quant import black76
from .util import atm_strike, chain_t_years, effective_iv


@dataclass
class ImpliedDistribution:
    future_price: float
    t_years: float
    atm_iv: float | None
    em_atm_iv: float | None
    em_straddle: float | None
    density: list[tuple[float, float]] = field(default_factory=list)  # (strike, pdf), normalized
    _widths: list[float] = field(default_factory=list, repr=False)
    needs_real_world_calibration: bool = True

    def prob_above(self, level: float) -> float | None:
        """Risk-neutral probability the underlying expires above `level`."""
        if not self.density:
            return None
        p = sum(pdf * w for (k, pdf), w in zip(self.density, self._widths, strict=True) if k > level)
        return max(0.0, min(1.0, p))

    def prob_inside(self, lo: float, hi: float) -> float | None:
        if not self.density:
            return None
        p = sum(pdf * w for (k, pdf), w in zip(self.density, self._widths, strict=True) if lo <= k <= hi)
        return max(0.0, min(1.0, p))


def expected_move_atm_iv(F: float, atm_iv: float | None, t: float) -> float | None:
    if atm_iv is None or t <= 0:
        return None
    return F * atm_iv * math.sqrt(t)


def _atm_straddle(chain: OptionChain, F: float, t: float, r: float) -> float | None:
    k = atm_strike(chain)
    row = next((x for x in chain.rows if x.strike == k), None)
    if row is None:
        return None
    civ = effective_iv(row.call, F, k, t, r)
    piv = effective_iv(row.put, F, k, t, r)
    if civ is None or piv is None:
        return None
    call = float(black76.price(OptionType.CALL, F, k, t, r, civ))
    put = float(black76.price(OptionType.PUT, F, k, t, r, piv))
    return call + put


def _rnd(chain: OptionChain, F: float, t: float, r: float):
    """Breeden-Litzenberger density from Black-76 model call prices across strikes."""
    pts = []
    for row in sorted(chain.rows, key=lambda x: x.strike):
        iv = effective_iv(row.call, F, row.strike, t, r)
        if iv is None:
            iv = effective_iv(row.put, F, row.strike, t, r)  # fall back to put IV (same vol surface)
        if iv is None:
            continue
        c = float(black76.price(OptionType.CALL, F, row.strike, t, r, iv))
        pts.append((row.strike, c))
    if len(pts) < 3:
        return [], []

    df = math.exp(r * t)  # e^{+rt}: undo discounting in the BL formula
    ks = [k for k, _ in pts]
    cs = [c for _, c in pts]
    density: list[tuple[float, float]] = []
    widths: list[float] = []
    for i in range(1, len(pts) - 1):
        x0, x1, x2 = ks[i - 1], ks[i], ks[i + 1]
        y0, y1, y2 = cs[i - 1], cs[i], cs[i + 1]
        # Non-uniform second derivative.
        d2 = 2.0 * (
            y0 / ((x1 - x0) * (x2 - x0))
            - y1 / ((x1 - x0) * (x2 - x1))
            + y2 / ((x2 - x1) * (x2 - x0))
        )
        pdf = max(0.0, df * d2)
        density.append((x1, pdf))
        widths.append((x2 - x0) / 2.0)

    mass = sum(pdf * w for (_, pdf), w in zip(density, widths, strict=True))
    if mass > 0:
        density = [(k, pdf / mass) for k, pdf in density]
    return density, widths


def implied_distribution(chain: OptionChain) -> ImpliedDistribution:
    F, r = chain.future_price, chain.risk_free_rate
    t = max(chain_t_years(chain), 1e-9)
    from .vol import atm_iv as _atm_iv  # local import avoids a module cycle

    aiv = _atm_iv(chain)
    density, widths = _rnd(chain, F, t, r)
    return ImpliedDistribution(
        future_price=F,
        t_years=t,
        atm_iv=aiv,
        em_atm_iv=expected_move_atm_iv(F, aiv, t),
        em_straddle=_atm_straddle(chain, F, t, r),
        density=density,
        _widths=widths,
    )
