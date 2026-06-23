"""Black-76 option pricing, Greeks, and implied-vol solver on the FUTURES price.

Indian index options are European and settled off the futures, so we price with
**Black-76** (the forward-price formulation), never Black-Scholes on spot. The forward
``F`` is a first-class input; callers resolve it via :func:`anvil.engine.forward.resolve_forward`
(a traded future when available, else a tagged cost-of-carry forward).

This engine is grafted from the validated OIP implementation and is independently checked
by the test suite: finite-difference cross-checks of every Greek, put-call parity, py_vollib
agreement (when installed), and IV round-trip.

Conventions returned by :func:`compute_greeks` (display units):
  delta, gamma : per ₹1 move in the forward
  vega         : per 1 percentage-point (1 vol) change in IV
  theta        : per calendar day
  rho          : per 1 percentage-point change in the rate

Low-level functions (:func:`price`, :func:`delta`, ...) return RAW academic units and are
NumPy-vectorized over K/sigma so GEX and distribution code can call them efficiently.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

from ..models import Greeks, OptionType

ENGINE_VERSION = "black76-1.0.0"

# Optional third-party Black-76 backend (the `black` module in vollib / py_vollib).
try:  # pragma: no cover - environment dependent
    from vollib.black import black as _pv_black  # noqa: F401
    from vollib.black.implied_volatility import implied_volatility as _pv_iv

    _HAS_PYVOLLIB = True
except Exception:  # pragma: no cover
    try:
        from py_vollib.black import black as _pv_black  # noqa: F401
        from py_vollib.black.implied_volatility import implied_volatility as _pv_iv

        _HAS_PYVOLLIB = True
    except Exception:
        _HAS_PYVOLLIB = False


def _is_call(option_type) -> bool:
    if isinstance(option_type, OptionType):
        return option_type == OptionType.CALL
    return str(option_type).strip().lower() in ("c", "call", "ce")


def _flag(option_type) -> str:
    return "c" if _is_call(option_type) else "p"


def _validate(F, K, T, r, sigma=None) -> None:
    """Scalar guards against NaN / percent-vs-decimal mistakes silently mispricing a chain."""
    if not np.isfinite(F) or F <= 0:
        raise ValueError(f"Futures price F must be finite and > 0, got {F}")
    if not np.isfinite(K) or K <= 0:
        raise ValueError(f"Strike K must be finite and > 0, got {K}")
    if not np.isfinite(T) or T <= 0:
        raise ValueError(f"Time to expiry T (years) must be finite and > 0, got {T}")
    if not np.isfinite(r) or not (-0.5 < r < 1.0):
        raise ValueError(f"Rate r must be a decimal within (-0.5, 1.0), got {r}")
    if sigma is not None and (not np.isfinite(sigma) or sigma <= 0):
        raise ValueError(f"Volatility sigma must be finite and > 0, got {sigma}")


def _d1_d2(F, K, T, sigma):
    F = np.asarray(F, dtype=float)
    K = np.asarray(K, dtype=float)
    T = np.asarray(T, dtype=float)
    sigma = np.asarray(sigma, dtype=float)
    srt = sigma * np.sqrt(T)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1 = (np.log(F / K) + 0.5 * sigma * sigma * T) / srt
        d2 = d1 - srt
    return d1, d2


def price(option_type, F, K, T, r=0.065, sigma=0.15):
    """Black-76 European option price (discounted). Vectorized over K/sigma."""
    d1, d2 = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    if _is_call(option_type):
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def delta(option_type, F, K, T, r, sigma):
    d1, _ = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    return df * norm.cdf(d1) if _is_call(option_type) else -df * norm.cdf(-d1)


def gamma(F, K, T, r, sigma):
    """Gamma w.r.t. the forward. Identical for calls and puts."""
    d1, _ = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    return df * norm.pdf(d1) / (F * sigma * np.sqrt(T))


def vega(F, K, T, r, sigma):
    """Raw vega: dPrice per 1.0 change in vol. Divide by 100 for per-1%."""
    d1, _ = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    return df * F * norm.pdf(d1) * np.sqrt(T)


def theta(option_type, F, K, T, r, sigma):
    """Raw calendar theta per year. Divide by 365 for per-day."""
    d1, d2 = _d1_d2(F, K, T, sigma)
    df = np.exp(-r * T)
    decay = -df * F * norm.pdf(d1) * sigma / (2.0 * np.sqrt(T))
    if _is_call(option_type):
        return decay + r * df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return decay + r * df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def rho(option_type, F, K, T, r, sigma):
    """Raw rho per 1.0 change in r. Under Black-76, rho == -T * price exactly."""
    return -T * price(option_type, F, K, T, r, sigma)


def compute_greeks(option_type, F, K, T, r=0.065, sigma=0.15) -> Greeks:
    """Scalar Greeks with display scaling (see module docstring)."""
    _validate(F, K, T, r, sigma)
    from .higher_order import charm, vanna, vomma

    return Greeks(
        delta=float(delta(option_type, F, K, T, r, sigma)),
        gamma=float(gamma(F, K, T, r, sigma)),
        theta=float(theta(option_type, F, K, T, r, sigma) / 365.0),
        vega=float(vega(F, K, T, r, sigma) / 100.0),
        rho=float(rho(option_type, F, K, T, r, sigma) / 100.0),
        vanna=float(vanna(F, K, T, r, sigma)),
        charm=float(charm(option_type, F, K, T, r, sigma) / 365.0),
        vomma=float(vomma(F, K, T, r, sigma)),
    )


def implied_vol(market_price, option_type, F, K, T, r=0.065) -> float:
    """Recover IV from a market price (Black-76). Returns NaN if no arbitrage-free solution."""
    if T is None or T <= 0 or market_price is None or market_price <= 0:
        return float("nan")
    flag = _flag(option_type)
    if _HAS_PYVOLLIB:
        try:
            return float(_pv_iv(market_price, F, K, r, T, flag))
        except Exception:
            pass

    def obj(s):
        return float(price(option_type, F, K, T, r, s)) - market_price

    lo, hi = 1e-9, 10.0
    try:
        if obj(lo) > 0 or obj(hi) < 0:
            return float("nan")
        return float(brentq(obj, lo, hi, xtol=1e-10, rtol=1e-12, maxiter=200))
    except (ValueError, RuntimeError):
        return float("nan")
