"""Market-implied probability distribution (Breeden-Litzenberger) + expected move.

Breeden-Litzenberger (1978): the risk-neutral density is the discounted second derivative of
the call price w.r.t. strike, ``RND(K) = e^{rT} · d²C/dK²``. We price calls with **Black-76 on
the forward**, so the density is over terminal forward (= settlement) values and its mean ≈ F.

Honest caveats:
  * This is the **risk-neutral** density (embeds a risk premium), not the real-world one —
    present probabilities as "market-implied".
  * Discrete, noisy strikes make a naive 2nd difference explode, so we smooth the IV smile first
    (cubic spline over strike), reprice on a dense grid, then differentiate — which reintroduces
    modeling choices; keep that transparent.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.interpolate import interp1d

try:  # NumPy 2.0 renamed trapz -> trapezoid
    from numpy import trapezoid as _trapz
except ImportError:  # pragma: no cover - NumPy < 2.0
    from numpy import trapz as _trapz

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from . import greeks as gk
from .forward import resolve_forward
from .util import year_fraction


@dataclass
class ImpliedDistribution:
    strikes: np.ndarray
    density: np.ndarray
    spot: float
    forward: float
    forward_source: str
    expiry_T: float
    expected_move_1sigma: float  # RND std
    em_straddle: float
    em_atm_iv: float | None  # F * atm_iv * sqrt(T)
    atm_iv: float | None
    extra: dict = field(default_factory=dict)

    def prob_between(self, lo: float, hi: float) -> float:
        mask = (self.strikes >= lo) & (self.strikes <= hi)
        if not mask.any():
            return 0.0
        return float(_trapz(self.density[mask], self.strikes[mask]))

    def prob_above(self, level: float) -> float:
        mask = self.strikes >= level
        return float(_trapz(self.density[mask], self.strikes[mask])) if mask.any() else 0.0

    def prob_below(self, level: float) -> float:
        return max(0.0, 1.0 - self.prob_above(level))


def _smile(chain: OptionChain, F, T, r):
    """Build an IV(strike) interpolator from the chain (prefer OTM wings around the forward)."""
    pts: dict[float, float] = {}
    for row in chain.rows:
        otm = (row.option_type == OptionType.PUT and row.strike <= F) or (
            row.option_type == OptionType.CALL and row.strike >= F
        )
        if not otm:
            continue
        iv = row.iv
        if (iv is None or iv <= 0) and row.ltp:
            iv = gk.implied_vol(row.ltp, row.option_type, F, row.strike, T, r)
        if iv is not None and iv == iv and iv > 0:
            pts[row.strike] = iv
    if len(pts) < 4:
        return None
    ks = np.array(sorted(pts))
    vs = np.array([pts[k] for k in ks])
    return interp1d(ks, vs, kind="cubic", fill_value="extrapolate", bounds_error=False), ks


def implied_distribution(
    chain: OptionChain, r: float | None = None, q: float | None = None, grid: int = 500
) -> ImpliedDistribution | None:
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
    F, F_src = resolve_forward(chain, r, q)

    built = _smile(chain, F, T, r)
    atm_iv = _atm_iv(chain, F, T, r)
    if built is None:
        return None
    smile, ks = built

    lo, hi = ks.min(), ks.max()
    K = np.linspace(lo, hi, grid)
    iv = np.clip(smile(K), 1e-3, 5.0)
    calls = gk.price(OptionType.CALL, F, K, T, r, iv)

    dK = K[1] - K[0]
    d2 = np.gradient(np.gradient(calls, dK), dK)
    rnd = np.exp(r * T) * d2
    rnd = np.clip(rnd, 0.0, None)

    area = _trapz(rnd, K)
    if area <= 0:
        return None
    density = rnd / area

    mean = _trapz(K * density, K)
    var = _trapz((K - mean) ** 2 * density, K)
    std = float(np.sqrt(max(var, 0.0)))

    em_atm_iv = float(F * atm_iv * np.sqrt(T)) if atm_iv else None

    return ImpliedDistribution(
        strikes=K,
        density=density,
        spot=chain.spot,
        forward=F,
        forward_source=F_src,
        expiry_T=T,
        expected_move_1sigma=std,
        em_straddle=_atm_straddle(chain),
        em_atm_iv=em_atm_iv,
        atm_iv=atm_iv,
    )


def _atm_iv(chain: OptionChain, F, T, r) -> float | None:
    atm = chain.atm_strike()
    ivs = []
    for ot in (OptionType.CALL, OptionType.PUT):
        row = chain.row(atm, ot)
        if row is None:
            continue
        iv = row.iv
        if (iv is None or iv <= 0) and row.ltp:
            iv = gk.implied_vol(row.ltp, ot, F, atm, T, r)
        if iv and iv == iv and iv > 0:
            ivs.append(iv)
    return float(np.mean(ivs)) if ivs else None


def _atm_straddle(chain: OptionChain) -> float:
    atm = chain.atm_strike()
    c = chain.row(atm, OptionType.CALL)
    p = chain.row(atm, OptionType.PUT)
    cp = (c.ltp or 0.0) if c else 0.0
    pp = (p.ltp or 0.0) if p else 0.0
    return float(cp + pp)
