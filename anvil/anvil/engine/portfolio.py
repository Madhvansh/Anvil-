"""Beta-weighted portfolio Greeks — the founder's "beta + gamma" feature.

Beta is NOT an option Greek; it's a market-sensitivity coefficient. "Beta-weighted
Greeks" (tastytrade) normalize every position's exposure to a single benchmark
(NIFTY / BANKNIFTY) so a multi-underlying book has one comparable risk number.

Standard beta-weighted delta (in benchmark-share terms)::

    BWD_i = position_delta_shares_i * beta_i * (underlying_price_i / benchmark_price)

We aggregate raw Greeks too, and express beta-weighted delta in benchmark *index
points* and *lots*. Beta-weighting gamma/theta/vega is less standardized — we expose
them clearly labeled as "benchmark-normalized", not a market standard.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..config import SETTINGS, lot_size
from ..models import Position
from . import greeks as gk
from .util import year_fraction


@dataclass
class PortfolioRisk:
    net_delta: float  # raw, in shares-equivalent
    net_gamma: float
    net_theta: float  # per day
    net_vega: float  # per 1%
    beta_weighted_delta: float  # in benchmark shares
    bwd_index_points: float  # P&L per 1 index point ~ beta_weighted_delta
    bwd_lots: float  # benchmark-lot equivalent
    benchmark: str
    benchmark_price: float
    per_position: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def _position_greeks(p: Position, r: float, now: str | None):
    """Per-share Greeks for the position's instrument.

    For options we price with Black-76 using the position's underlying as the forward
    proxy (we lack a per-name future at the position level; spot≈forward intraday).
    """
    if p.instrument_type in ("EQ", "FUT"):
        # linear instruments: delta 1/share, no convexity
        return dict(delta=1.0, gamma=0.0, theta=0.0, vega=0.0)
    # option
    F = p.underlying_price or p.ltp
    if not (p.strike and p.expiry and F):
        return dict(delta=0.0, gamma=0.0, theta=0.0, vega=0.0)
    T = max(year_fraction(p.expiry, now), 1e-6)
    sigma = p.iv
    if (sigma is None or sigma <= 0) and p.ltp:
        sigma = gk.implied_vol(p.ltp, p.option_type, F, p.strike, T, r)
    if not sigma or sigma != sigma or sigma <= 0:
        sigma = 0.15
    g = gk.compute_greeks(p.option_type, F, p.strike, T, r, sigma)
    return dict(delta=g.delta, gamma=g.gamma, theta=g.theta, vega=g.vega)


def beta_weighted_greeks(
    positions: list[Position],
    benchmark: str = "NIFTY",
    benchmark_price: float = 0.0,
    r: float | None = None,
    now: str | None = None,
) -> PortfolioRisk:
    r = SETTINGS.risk_free_rate if r is None else r

    net = dict(delta=0.0, gamma=0.0, theta=0.0, vega=0.0)
    bwd = 0.0
    per_position = []
    notes = []

    if benchmark_price <= 0:
        notes.append("benchmark_price not provided — beta-weighted delta will be 0")

    for p in positions:
        per_share = _position_greeks(p, r, now)
        qty = p.quantity  # signed, already in shares for F&O
        delta_sh = per_share["delta"] * qty
        gamma_sh = per_share["gamma"] * qty
        theta_sh = per_share["theta"] * qty
        vega_sh = per_share["vega"] * qty

        net["delta"] += delta_sh
        net["gamma"] += gamma_sh
        net["theta"] += theta_sh
        net["vega"] += vega_sh

        und_px = p.underlying_price or p.ltp or 0.0
        if benchmark_price > 0 and und_px > 0:
            bw = delta_sh * p.beta * (und_px / benchmark_price)
        else:
            bw = 0.0
        bwd += bw

        per_position.append(
            {
                "symbol": p.symbol,
                "qty": qty,
                "delta_shares": round(delta_sh, 2),
                "gamma_shares": round(gamma_sh, 4),
                "theta_day": round(theta_sh, 2),
                "vega_pct": round(vega_sh, 2),
                "beta_weighted_delta": round(bw, 2),
            }
        )

    blot = lot_size(benchmark, 1)
    return PortfolioRisk(
        net_delta=net["delta"],
        net_gamma=net["gamma"],
        net_theta=net["theta"],
        net_vega=net["vega"],
        beta_weighted_delta=bwd,
        bwd_index_points=bwd,  # ~ ₹ P&L per 1 index point (1 share == 1 point)
        bwd_lots=(bwd / blot) if blot else bwd,
        benchmark=benchmark,
        benchmark_price=benchmark_price,
        per_position=per_position,
        notes=notes,
    )
