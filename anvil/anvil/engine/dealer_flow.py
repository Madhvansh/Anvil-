"""Dealer-hedging-flow stack — vanna/charm exposure + gamma-flip levels (Black-76).

Innovation I.1. GEX already reads dealer GAMMA (how hedging reacts to spot moves). This adds the next
order: how dealer hedging reacts to **vol** and **time** — the durable, economically-grounded edge
(dealers *must* re-hedge):

- **Vanna exposure** — net dealer delta change per 1 IV percentage-point. As IV moves (e.g. post-event
  crush), short-vanna dealers must trade the underlying → a predictable drift.
- **Charm exposure** — net dealer delta drift per calendar day. Drives end-of-day / expiry **pinning**.
- **Gamma-flip levels** — the zero-gamma strike as an intraday support/resistance band.

Sign convention mirrors ``engine.gex``: dealers long calls / short puts (call +, put −, × ``dealer_sign``).
Scaling is in DELTA units (shares-equivalent), documented per field. INDIA-UNVALIDATED for directional
use (the research report warns SPX dealer mechanics may not transfer; Jane Street showed large players
can dominate expiries) → callers tier the directional read CONFIRMATION until the live curve backs it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from . import greeks as gk
from . import higher_order as ho
from .forward import resolve_forward
from .gex import GEXResult, compute_gex
from .util import year_fraction


@dataclass
class DealerFlowResult:
    total_vanna_exposure: float        # net dealer Δ change per +1 IV percentage-point (shares-equiv)
    total_charm_exposure: float        # net dealer Δ drift per calendar day (shares-equiv)
    per_strike_vanna: dict[float, float]
    per_strike_charm: dict[float, float]
    vanna_walls: list[tuple[float, float]]   # strikes with the largest |vanna exposure|
    charm_walls: list[tuple[float, float]]   # strikes with the largest |charm exposure|
    zero_gamma_flip: float | None
    spot: float
    forward: float
    forward_source: str
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_vanna_exposure": self.total_vanna_exposure,
            "total_charm_exposure": self.total_charm_exposure,
            "vanna_walls": self.vanna_walls,
            "charm_walls": self.charm_walls,
            "zero_gamma_flip": self.zero_gamma_flip,
            "spot": self.spot,
            "forward": self.forward,
            "forward_source": self.forward_source,
            "extra": self.extra,
        }


def _row_iv(row, F, T, r) -> float | None:
    if row.iv is not None and row.iv > 0:
        return row.iv
    if row.ltp is not None and row.ltp > 0:
        iv = gk.implied_vol(row.ltp, row.option_type, F, row.strike, T, r)
        return iv if iv == iv else None  # filter NaN
    return None


def compute_dealer_flow(
    chain: OptionChain,
    r: float | None = None,
    q: float | None = None,
    dealer_sign: int = 1,
    n_walls: int = 3,
    gex_result: GEXResult | None = None,
) -> DealerFlowResult:
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
    spot = chain.spot
    F, F_src = resolve_forward(chain, r, q)
    lot = chain.lot_size or 1

    per_vanna: dict[float, float] = {}
    per_charm: dict[float, float] = {}
    for row in chain.rows:
        iv = _row_iv(row, F, T, r)
        if iv is None:
            continue
        v = float(ho.vanna(F, row.strike, T, r, iv))
        c = float(ho.charm(row.option_type, F, row.strike, T, r, iv))
        pos = (+1 if row.option_type == OptionType.CALL else -1) * dealer_sign
        # Vanna: Δ change per +1 IV pt = vanna(per 1.0 vol) × 0.01. Charm: per-day Δ bleed = −charm/365.
        per_vanna[row.strike] = per_vanna.get(row.strike, 0.0) + pos * v * 0.01 * row.oi * lot
        per_charm[row.strike] = per_charm.get(row.strike, 0.0) + pos * (-c / 365.0) * row.oi * lot

    total_vanna = float(sum(per_vanna.values()))
    total_charm = float(sum(per_charm.values()))
    vanna_walls = sorted(per_vanna.items(), key=lambda kv: abs(kv[1]), reverse=True)[:n_walls]
    charm_walls = sorted(per_charm.items(), key=lambda kv: abs(kv[1]), reverse=True)[:n_walls]

    if gex_result is None:
        gex_result = compute_gex(chain, r, q, dealer_sign, n_walls)
    flip = gex_result.zero_gamma_flip

    return DealerFlowResult(
        total_vanna_exposure=total_vanna,
        total_charm_exposure=total_charm,
        per_strike_vanna=per_vanna,
        per_strike_charm=per_charm,
        vanna_walls=vanna_walls,
        charm_walls=charm_walls,
        zero_gamma_flip=flip,
        spot=spot,
        forward=F,
        forward_source=F_src,
    )


def dealer_hedge_drift(result: DealerFlowResult, *, iv_change_pts: float = 0.0, days: float = 1.0) -> dict:
    """Mechanical estimate of the net dealer delta accumulated over an IV move + elapsed time, and the
    re-hedging flow it forces. To stay hedged, dealers trade OPPOSITE the delta they accumulate:
    positive accumulated Δ → they SELL the underlying (downward pressure), and vice-versa.

    Honest label: a mechanical hedging estimate, NOT a certified directional edge (india_unvalidated).
    """
    delta_accum = result.total_vanna_exposure * iv_change_pts + result.total_charm_exposure * days
    if delta_accum > 0:
        flow = "sell_underlying"
    elif delta_accum < 0:
        flow = "buy_underlying"
    else:
        flow = "neutral"
    return {
        "delta_accumulated": float(delta_accum),
        "rehedge_flow": flow,
        "pressure": float(-delta_accum),
        "note": "mechanical_hedging_estimate_india_unvalidated",
    }


def gamma_flip_levels(zero_gamma_flip: float | None, spot: float) -> dict | None:
    """Gamma-flip as an intraday support/resistance read: distance of spot from the flip, and which
    regime spot is in (above = positive-gamma / pinned / mean-reverting; below = negative / trending)."""
    if zero_gamma_flip is None or spot <= 0:
        return None
    dist = float((spot - zero_gamma_flip) / spot)
    return {
        "flip": float(zero_gamma_flip),
        "spot": float(spot),
        "distance": dist,                       # +ve: spot above flip (pinned regime)
        "regime": "positive_gamma_pinned" if dist >= 0 else "negative_gamma_trending",
        "acts_as": "support" if dist >= 0 else "resistance",
    }
