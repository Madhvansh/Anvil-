"""IV-crush warning — is option premium expensive and at risk of collapsing?

Blends ATM IV rank/percentile (vs supplied history), proximity to expiry, and front-vs-back
backwardation into a 0-100 crush score + a plain-language warning. History and term structure
are optional inputs (the SnapshotStore supplies IV history; term_structure supplies front/back).
"""

from __future__ import annotations

from ..config import SETTINGS
from ..models import OptionChain
from .forward import resolve_forward
from .implied_dist import _atm_iv
from .util import year_fraction
from .vol import iv_percentile, iv_rank


def iv_crush_warning(
    chain: OptionChain,
    history_iv: list[float] | None = None,
    front_back: tuple[float, float] | None = None,
    r: float | None = None,
) -> dict:
    r = SETTINGS.risk_free_rate if r is None else r
    T = year_fraction(chain.expiry, chain.timestamp)
    days = T * 365.0
    F, _ = resolve_forward(chain)
    atm_iv = _atm_iv(chain, F, T, r)

    rank = iv_rank(atm_iv, history_iv) if (atm_iv and history_iv) else None
    pctile = iv_percentile(atm_iv, history_iv) if (atm_iv and history_iv) else None
    backwardation = (front_back[0] - front_back[1]) if front_back else None

    # Heuristic 0-100 crush score: rich IV + near expiry + front richer than back.
    score = 0.0
    if rank is not None:
        score += 0.5 * rank
    elif atm_iv:
        score += 0.5 * min(100.0, atm_iv * 300.0)  # fallback when no history (15% -> ~45)
    if days <= 2:
        score += 30.0
    elif days <= 5:
        score += 15.0
    if backwardation and backwardation > 0:
        score += min(20.0, backwardation * 200.0)
    score = max(0.0, min(100.0, score))

    if score >= SETTINGS.iv_crush_threshold:
        level, msg = "high", "Premium looks rich and time/term structure favour a sharp IV drop — crush risk is high."
    elif score >= 40:
        level, msg = "medium", "Premium is somewhat elevated; watch for IV compression into expiry."
    else:
        level, msg = "low", "Premium is not unusually rich; crush risk is limited."

    return {
        "underlying": chain.underlying,
        "atm_iv": round(atm_iv, 4) if atm_iv else None,
        "iv_rank": round(rank, 1) if rank is not None else None,
        "iv_percentile": round(pctile, 1) if pctile is not None else None,
        "days_to_expiry": round(days, 2),
        "backwardation": round(backwardation, 4) if backwardation is not None else None,
        "crush_score": round(score, 1),
        "level": level,
        "warning": msg,
    }
