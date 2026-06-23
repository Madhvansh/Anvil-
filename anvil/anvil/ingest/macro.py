"""Macro pricing inputs: risk-free rate and the futures-implied forward.

The risk-free rate (for Black-Scholes) is taken from settings (default ~6.5%, an India
T-bill / MIBOR proxy). The forward is best taken from the underlying's near futures price
when available; otherwise from carry. Replace the rate source with a live MIBOR/T-bill
feed in production.
"""

from __future__ import annotations

from ..config import SETTINGS


def risk_free_rate() -> float:
    return SETTINGS.risk_free_rate


def dividend_yield() -> float:
    return SETTINGS.dividend_yield


def forward_from_future(future_price: float | None, spot: float) -> float:
    """Prefer the traded future as the forward; fall back to spot."""
    return float(future_price) if future_price and future_price > 0 else float(spot)


def forward_from_carry(spot: float, T: float, r: float | None = None, q: float | None = None) -> float:
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    import math

    return float(spot * math.exp((r - q) * T))
