"""Second-order Greeks (Black-76, on the futures price): vanna, charm, vomma.

These drive the vanna/charm "walls" overlay (how dealer hedging shifts as the forward,
time, and vol move). All functions are NumPy-vectorized and return RAW values:
  - vanna : d(delta)/d(sigma) == d(vega)/d(forward)
  - charm : d(delta)/d(T), per year (negate & /365 for per-day delta decay)
  - vomma : d(vega)/d(sigma)

Validated against finite differences of the analytic first-order Greeks in the test suite.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm

from .greeks import _d1_d2, _is_call


def vanna(F, K, T, r, sigma):
    d1, d2 = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    return -df * norm.pdf(d1) * d2 / sigma


def vomma(F, K, T, r, sigma):
    d1, d2 = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    vega_raw = df * F * norm.pdf(d1) * np.sqrt(T)
    return vega_raw * d1 * d2 / sigma


def charm(option_type, F, K, T, r, sigma):
    """d(delta)/d(T), per year, for Black-76. For per-calendar-day delta bleed use ``-charm/365``."""
    d1, _ = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    a = np.log(np.asarray(F, float) / np.asarray(K, float))
    # d(d1)/dT for Black-76 (no drift term): d1 = a/(sigma*sqrt(T)) + 0.5*sigma*sqrt(T)
    dd1_dT = (1.0 / (2.0 * np.sqrt(T))) * (0.5 * sigma - a / (sigma * T))
    pdf = norm.pdf(d1)
    if _is_call(option_type):
        return -r * df * norm.cdf(d1) + df * pdf * dd1_dT
    return r * df * norm.cdf(-d1) + df * pdf * dd1_dT
