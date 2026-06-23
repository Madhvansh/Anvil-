"""Fused regime read — combines dealer positioning, the implied distribution, and OI
into a single, explainable "regime" label with calibrated probabilities.

This is deliberately a transparent, rules-based first cut (NOT a black-box predictor).
Every output carries its drivers so the AI layer can explain it and the prediction
ledger can later score its calibration. It is a *regime prior*, not a price oracle —
and it never emits buy/sell calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..models import OptionChain
from . import oi as oi_mod
from .gex import GEXResult, compute_gex
from .implied_dist import ImpliedDistribution, implied_distribution


@dataclass
class RegimeRead:
    label: str  # e.g. "positive_gamma_mean_revert"
    spot: float
    zero_gamma_flip: float | None
    total_gex: float
    pcr_oi: float | None
    max_pain: float | None
    expected_move_1sigma: float | None
    prob_inside_em: float | None  # market-implied P(close within ±1 EM by expiry)
    drivers: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


def read_regime(
    chain: OptionChain,
    gex: GEXResult | None = None,
    dist: ImpliedDistribution | None = None,
) -> RegimeRead:
    gex = gex or compute_gex(chain)
    dist = dist if dist is not None else implied_distribution(chain)
    spot = chain.spot
    drivers: list[str] = []

    above_flip = gex.zero_gamma_flip is not None and spot >= gex.zero_gamma_flip
    if gex.total_gex > 0 and above_flip:
        label = "positive_gamma_mean_revert"
        drivers.append(
            f"Net GEX positive ({gex.total_gex:,.0f}) and spot {spot:,.0f} above flip "
            f"{gex.zero_gamma_flip:,.0f} → dealers hedge against moves → pinning / lower vol."
        )
    elif gex.total_gex < 0 or (gex.zero_gamma_flip and spot < gex.zero_gamma_flip):
        label = "negative_gamma_trend_amplify"
        flip_txt = f"{gex.zero_gamma_flip:,.0f}" if gex.zero_gamma_flip else "n/a"
        drivers.append(
            f"Net GEX {gex.total_gex:,.0f} / spot {spot:,.0f} vs flip {flip_txt} → dealers "
            f"hedge with moves → trend-amplifying / higher vol."
        )
    else:
        label = "neutral_mixed"
        drivers.append("Mixed dealer positioning — no clear gamma regime.")

    pcr = oi_mod.pcr_oi(chain)
    mp = oi_mod.max_pain(chain)
    if pcr is not None:
        drivers.append(f"PCR(OI) {pcr:.2f} ({'put-heavy/supportive' if pcr > 1 else 'call-heavy/cap'}).")
    if mp is not None:
        drivers.append(f"Max pain {mp:,.0f} (expiry magnet).")

    em = prob_inside = None
    if dist is not None:
        em = dist.expected_move_1sigma
        prob_inside = dist.prob_between(spot - em, spot + em)
        drivers.append(
            f"Market-implied ±1σ move ≈ {em:,.0f} pts; P(close within band by expiry) ≈ "
            f"{prob_inside*100:.0f}%."
        )

    return RegimeRead(
        label=label,
        spot=spot,
        zero_gamma_flip=gex.zero_gamma_flip,
        total_gex=gex.total_gex,
        pcr_oi=pcr,
        max_pain=mp,
        expected_move_1sigma=em,
        prob_inside_em=prob_inside,
        drivers=drivers,
    )
