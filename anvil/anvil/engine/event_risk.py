"""Event / expiry risk — how dangerous is the run into expiry right now?

Combines days-to-expiry, ATM theta burn, market-implied expected move, and pin pressure
(proximity to max-pain and the zero-gamma flip) into a traffic-light read. Reuses the engine
primitives; adds no new pricing.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from . import greeks as gk
from . import oi as oi_mod
from .forward import resolve_forward
from .gex import compute_gex
from .implied_dist import _atm_iv, implied_distribution
from .util import year_fraction


def event_risk(chain: OptionChain, r: float | None = None) -> dict:
    r = SETTINGS.risk_free_rate if r is None else r
    T = year_fraction(chain.expiry, chain.timestamp)
    days = T * 365.0
    F, _ = resolve_forward(chain)
    atm_iv = _atm_iv(chain, F, T, r) or 0.0

    dist = implied_distribution(chain)
    em = dist.expected_move_1sigma if dist else None
    em_pct = (em / chain.spot) if (em and chain.spot) else None

    gex = compute_gex(chain)
    flip = gex.zero_gamma_flip
    mp = oi_mod.max_pain(chain)
    dist_mp = abs(chain.spot - mp) / chain.spot if (mp and chain.spot) else None
    dist_flip = abs(chain.spot - flip) / chain.spot if (flip and chain.spot) else None

    # ATM straddle theta/day (negative = decay), as a % of the straddle premium.
    atm = chain.atm_strike()
    theta_day = 0.0
    if atm_iv > 0:
        for ot in (OptionType.CALL, OptionType.PUT):
            theta_day += gk.compute_greeks(ot, F, atm, max(T, 1e-6), r, atm_iv).theta
    straddle = 0.0
    for ot in (OptionType.CALL, OptionType.PUT):
        row = chain.row(atm, ot)
        straddle += (row.ltp or 0.0) if row else 0.0
    theta_burn_pct = abs(theta_day) / straddle if straddle else None

    pin = bool(dist_mp is not None and dist_mp < 0.005)  # within 0.5% of max pain
    if days <= 1.0 or (theta_burn_pct or 0) > 0.08:
        level = "high"
    elif days <= 3.0 or pin or (dist_flip is not None and dist_flip < 0.003):
        level = "medium"
    else:
        level = "low"

    return {
        "underlying": chain.underlying,
        "days_to_expiry": round(days, 2),
        "expected_move_pct": round(em_pct, 4) if em_pct is not None else None,
        "max_pain": mp,
        "distance_to_max_pain_pct": round(dist_mp, 4) if dist_mp is not None else None,
        "zero_gamma_flip": flip,
        "distance_to_flip_pct": round(dist_flip, 4) if dist_flip is not None else None,
        "atm_theta_per_day": round(theta_day, 3),
        "theta_burn_pct": round(theta_burn_pct, 4) if theta_burn_pct is not None else None,
        "pin_risk": pin,
        "risk_level": level,
    }
