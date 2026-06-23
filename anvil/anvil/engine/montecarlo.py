"""Monte Carlo P&L — sample the terminal index from the MARKET-IMPLIED (Breeden-Litzenberger)
risk-neutral distribution, not a naive lognormal, then reprice the book to a horizon.

Outputs P(profit), expected P&L, percentiles, and VaR/CVaR with an honest caveat: this is the
risk-neutral terminal density (embeds a risk premium) with IV held constant — a risk map, not a
return forecast.
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from ..models import OptionChain, Position
from . import greeks as gk
from .implied_dist import implied_distribution
from .scenarios import _book_value, _foreign_unknown, _underlying_level
from .util import year_fraction

CAVEAT = (
    "Terminal index sampled from the market-implied (risk-neutral) distribution with IV held "
    "constant. This is a risk map, not a forecast of returns."
)


def _sample_terminal(strikes: np.ndarray, density: np.ndarray, n: int, rng: np.random.Generator) -> np.ndarray:
    # Inverse-CDF sample from the discrete RND over the strike grid.
    widths = np.diff(strikes)
    mass = (density[:-1] + density[1:]) / 2.0 * widths
    cdf = np.concatenate([[0.0], np.cumsum(mass)])
    if cdf[-1] <= 0:
        return np.full(n, float(strikes[len(strikes) // 2]))
    cdf = cdf / cdf[-1]
    return np.interp(rng.random(n), cdf, strikes)


def mc_pnl(
    chain: OptionChain,
    positions: list[Position] | None,
    horizon_days: float = 7.0,
    n_paths: int = 10000,
    seed: int | None = None,
    r: float | None = None,
) -> dict:
    r = SETTINGS.risk_free_rate if r is None else r
    positions = positions or []
    dist = implied_distribution(chain)
    if dist is None:
        return {"available": False, "note": "Insufficient option chain to build an implied distribution.", "caveat": CAVEAT}

    rng = np.random.default_rng(seed)
    samples = _sample_terminal(dist.strikes, dist.density, int(n_paths), rng)
    rel = samples / dist.forward - 1.0  # relative index move per path

    base = _book_value(positions, chain, 0.0, 0.0, 0.0, r)
    book = np.zeros(samples.shape[0], dtype=float)
    for p in positions:
        if p.instrument_type in ("EQ", "FUT"):
            book += _underlying_level(p, chain) * (1.0 + p.beta * rel) * p.quantity
        elif p.option_type is not None and p.strike is not None:
            if _foreign_unknown(p, chain):
                book += float(p.ltp or 0.0) * p.quantity  # hold flat at current mark
                continue
            level = _underlying_level(p, chain) * (1.0 + p.beta * rel)
            T = max(year_fraction(p.expiry or chain.expiry, chain.timestamp) - horizon_days / 365.0, 1e-6)
            sigma = max(p.iv or 0.15, 1e-3)
            book += np.asarray(gk.price(p.option_type, level, p.strike, T, r, sigma), dtype=float) * p.quantity

    pnl = book - base
    pcts = {f"p{q}": float(np.percentile(pnl, q)) for q in (5, 25, 50, 75, 95)}
    var95 = -pcts["p5"]
    tail = pnl[pnl <= pcts["p5"]]
    cvar95 = float(-tail.mean()) if tail.size else var95
    counts, edges = np.histogram(pnl, bins=25)

    return {
        "available": True,
        "underlying": chain.underlying,
        "n_paths": int(n_paths),
        "horizon_days": horizon_days,
        "base_value": round(base, 2),
        "expected_pnl": round(float(pnl.mean()), 2),
        "p_profit": round(float((pnl > 0).mean()), 4),
        "percentiles": {k: round(v, 2) for k, v in pcts.items()},
        "var_95": round(var95, 2),
        "cvar_95": round(cvar95, 2),
        "terminal": {"mean": round(float(samples.mean()), 2), "std": round(float(samples.std()), 2)},
        "histogram": {"edges": [round(float(e), 2) for e in edges], "counts": [int(c) for c in counts]},
        "has_positions": bool(positions),
        "caveat": CAVEAT,
    }
