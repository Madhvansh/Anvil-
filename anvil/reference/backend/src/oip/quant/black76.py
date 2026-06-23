"""Black-76 option pricing and Greeks on the FUTURES price.

Indian index options are priced/settled off futures, so we use Black-76 (the forward-price
formulation), never Black-Scholes on spot. See docs/decisions/0004-greeks-black76-pyvollib.md.

Units returned by this module are RAW academic units:
- price        : option premium (same currency units as F, K)
- delta, gamma : dimensionless
- vega         : dPrice per 1.00 (100%) change in volatility
- theta        : calendar theta per YEAR (negative for long options)
- rho          : dPrice per 1.00 (100%) change in the rate

Presentation scaling (theta/365, vega/100, rho/100) is applied by greeks_service, not here.

Pricing and implied vol use py_vollib when available (an independent, third-party Black-76
implementation); a self-contained SciPy/NumPy closed form is the fallback. The analytic Greeks are
computed here in closed form and are independently validated by the finite-difference test suite.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq
from scipy.stats import norm

from ..domain.enums import OptionType

ENGINE_VERSION = "black76-1.0.0"

# Optional third-party pricing/IV backend. The Black-1976 model (options on futures) is the
# `black` module in the vollib/py_vollib library (NOT a module literally named "black_76").
try:  # pragma: no cover - exercised by environment, not logic
    from vollib.black import black as _pv_black
    from vollib.black.implied_volatility import implied_volatility as _pv_iv

    _HAS_PYVOLLIB = True
except Exception:  # pragma: no cover
    try:
        from py_vollib.black import black as _pv_black
        from py_vollib.black.implied_volatility import implied_volatility as _pv_iv

        _HAS_PYVOLLIB = True
    except Exception:
        _HAS_PYVOLLIB = False


@dataclass(frozen=True)
class Greeks:
    """Raw-unit Black-76 result for one option leg."""

    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


_ALIASES = {"c": "c", "p": "p", "call": "c", "put": "p", "ce": "c", "pe": "p"}


def _flag(option_type: OptionType | str) -> str:
    if isinstance(option_type, OptionType):
        return option_type.value
    key = str(option_type).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(f"Unrecognized option type: {option_type!r}")


def _validate(F: float, K: float, t: float, r: float, sigma: float | None = None) -> None:
    if not math.isfinite(F) or F <= 0:
        raise ValueError(f"Futures price F must be finite and > 0, got {F}")
    if not math.isfinite(K) or K <= 0:
        raise ValueError(f"Strike K must be finite and > 0, got {K}")
    if not math.isfinite(t) or t <= 0:
        raise ValueError(f"Time to expiry t (years) must be finite and > 0, got {t}")
    # Guard against a percent-vs-decimal mistake or NaN silently mispricing the whole chain.
    if not math.isfinite(r) or not (-0.5 < r < 1.0):
        raise ValueError(f"Risk-free rate r must be finite and within (-0.5, 1.0) as a decimal, got {r}")
    if sigma is not None and (not math.isfinite(sigma) or sigma <= 0):
        raise ValueError(f"Volatility sigma must be finite and > 0, got {sigma}")


def _d1_d2(F: float, K: float, t: float, sigma: float) -> tuple[float, float]:
    srt = sigma * math.sqrt(t)
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * t) / srt
    return d1, d1 - srt


def _price_closed_form(flag: str, F: float, K: float, t: float, r: float, sigma: float) -> float:
    d1, d2 = _d1_d2(F, K, t, sigma)
    df = math.exp(-r * t)
    if flag == "c":
        return df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def price(option_type: OptionType | str, F: float, K: float, t: float, r: float, sigma: float) -> float:
    flag = _flag(option_type)
    _validate(F, K, t, r, sigma)
    if _HAS_PYVOLLIB:
        return float(_pv_black(flag, F, K, t, r, sigma))
    return _price_closed_form(flag, F, K, t, r, sigma)


def delta(option_type: OptionType | str, F: float, K: float, t: float, r: float, sigma: float) -> float:
    flag = _flag(option_type)
    _validate(F, K, t, r, sigma)
    d1, _ = _d1_d2(F, K, t, sigma)
    df = math.exp(-r * t)
    return df * norm.cdf(d1) if flag == "c" else -df * norm.cdf(-d1)


def gamma(F: float, K: float, t: float, r: float, sigma: float) -> float:
    _validate(F, K, t, r, sigma)
    d1, _ = _d1_d2(F, K, t, sigma)
    df = math.exp(-r * t)
    return df * norm.pdf(d1) / (F * sigma * math.sqrt(t))


def vega(F: float, K: float, t: float, r: float, sigma: float) -> float:
    """Raw vega: dPrice per 1.00 change in vol. Identical for calls and puts."""
    _validate(F, K, t, r, sigma)
    d1, _ = _d1_d2(F, K, t, sigma)
    df = math.exp(-r * t)
    return df * F * norm.pdf(d1) * math.sqrt(t)


def theta(option_type: OptionType | str, F: float, K: float, t: float, r: float, sigma: float) -> float:
    """Raw calendar theta per year = -dPrice/d(tau)."""
    flag = _flag(option_type)
    _validate(F, K, t, r, sigma)
    d1, d2 = _d1_d2(F, K, t, sigma)
    df = math.exp(-r * t)
    decay = -df * F * norm.pdf(d1) * sigma / (2.0 * math.sqrt(t))
    if flag == "c":
        return decay + r * df * (F * norm.cdf(d1) - K * norm.cdf(d2))
    return decay + r * df * (K * norm.cdf(-d2) - F * norm.cdf(-d1))


def rho(option_type: OptionType | str, F: float, K: float, t: float, r: float, sigma: float) -> float:
    """Raw rho per 1.00 change in r. Under Black-76, rho == -t * price exactly."""
    flag = _flag(option_type)
    _validate(F, K, t, r, sigma)
    return -t * _price_closed_form(flag, F, K, t, r, sigma)


def implied_vol(
    option_type: OptionType | str, market_price: float, F: float, K: float, t: float, r: float
) -> float:
    flag = _flag(option_type)
    _validate(F, K, t, r)
    if market_price <= 0:
        raise ValueError(f"market_price must be > 0, got {market_price}")

    if _HAS_PYVOLLIB:
        try:
            return float(_pv_iv(market_price, F, K, r, t, flag))
        except Exception:
            pass  # fall back to a robust bracketed solver

    def objective(sigma: float) -> float:
        return _price_closed_form(flag, F, K, t, r, sigma) - market_price

    lo, hi = 1e-9, 10.0
    if objective(lo) > 0 or objective(hi) < 0:
        raise ValueError("market_price is outside the Black-76 no-arbitrage range")
    return float(brentq(objective, lo, hi, xtol=1e-10, rtol=1e-12, maxiter=200))


def all_greeks(
    option_type: OptionType | str, F: float, K: float, t: float, r: float, sigma: float
) -> Greeks:
    flag = _flag(option_type)
    return Greeks(
        price=price(flag, F, K, t, r, sigma),
        delta=delta(flag, F, K, t, r, sigma),
        gamma=gamma(F, K, t, r, sigma),
        vega=vega(F, K, t, r, sigma),
        theta=theta(flag, F, K, t, r, sigma),
        rho=rho(flag, F, K, t, r, sigma),
    )
