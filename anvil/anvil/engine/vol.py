"""Volatility analytics: IV rank/percentile, realized vol, skew, term structure."""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from . import greeks as gk
from .forward import resolve_forward
from .util import year_fraction


def iv_rank(current_iv: float, history: list[float] | np.ndarray) -> float | None:
    """Where current IV sits in its [min, max] range over history (0..100)."""
    h = np.asarray([x for x in history if x == x], dtype=float)
    if h.size == 0:
        return None
    lo, hi = h.min(), h.max()
    if hi == lo:
        return 50.0
    return float(100.0 * (current_iv - lo) / (hi - lo))


def iv_percentile(current_iv: float, history: list[float] | np.ndarray) -> float | None:
    """Fraction of historical days IV was below current (0..100)."""
    h = np.asarray([x for x in history if x == x], dtype=float)
    if h.size == 0:
        return None
    return float(100.0 * np.mean(h < current_iv))


def realized_vol(closes: list[float] | np.ndarray, annualize: int = 252) -> float | None:
    """Close-to-close annualized realized volatility from a price series."""
    c = np.asarray(closes, dtype=float)
    if c.size < 2:
        return None
    rets = np.diff(np.log(c))
    return float(np.std(rets, ddof=1) * np.sqrt(annualize))


def vol_cone(closes: list[float] | np.ndarray, windows=(5, 10, 20, 60)) -> dict[int, dict]:
    """Realized-vol percentile cone across rolling windows."""
    c = np.asarray(closes, dtype=float)
    out: dict[int, dict] = {}
    log_c = np.log(c)
    for w in windows:
        if c.size <= w:
            continue
        rolling = []
        for i in range(w, c.size):
            seg = np.diff(log_c[i - w : i + 1])
            rolling.append(np.std(seg, ddof=1) * np.sqrt(252))
        rolling = np.asarray(rolling)
        if rolling.size:
            out[w] = {
                "min": float(rolling.min()),
                "p25": float(np.percentile(rolling, 25)),
                "median": float(np.median(rolling)),
                "p75": float(np.percentile(rolling, 75)),
                "max": float(rolling.max()),
                "current": float(rolling[-1]),
            }
    return out


def skew(chain: OptionChain, r: float | None = None, q: float | None = None) -> dict:
    """Risk-reversal style skew: OTM put IV minus OTM call IV ~25-delta wings.

    Positive => puts richer than calls (the usual equity-index fear skew).
    """
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
    F, _ = resolve_forward(chain, r, q)

    def iv_of(row):
        if row is None:
            return None
        iv = row.iv
        if (iv is None or iv <= 0) and row.ltp:
            iv = gk.implied_vol(row.ltp, row.option_type, F, row.strike, T, r)
        return iv if (iv and iv == iv and iv > 0) else None

    # crude 25-delta proxy: ~ATM ± one expected-move band
    atm = chain.atm_strike()
    put_target = atm * 0.97
    call_target = atm * 1.03
    put_strike = min((r_.strike for r_ in chain.puts()), key=lambda k: abs(k - put_target), default=None)
    call_strike = min((r_.strike for r_ in chain.calls()), key=lambda k: abs(k - call_target), default=None)
    put_iv = iv_of(chain.row(put_strike, OptionType.PUT)) if put_strike else None
    call_iv = iv_of(chain.row(call_strike, OptionType.CALL)) if call_strike else None
    rr = (put_iv - call_iv) if (put_iv and call_iv) else None
    return {
        "put_strike": put_strike,
        "put_iv": put_iv,
        "call_strike": call_strike,
        "call_iv": call_iv,
        "risk_reversal": rr,
    }


def term_structure(chains: list[OptionChain]) -> list[dict]:
    """ATM IV across expiries (front to back). Contango (rising) vs backwardation."""
    from .implied_dist import _atm_iv

    rows = []
    for ch in sorted(chains, key=lambda c: c.expiry):
        T = max(year_fraction(ch.expiry, ch.timestamp), 1e-6)
        F, _ = resolve_forward(ch, SETTINGS.risk_free_rate, SETTINGS.dividend_yield)
        rows.append({"expiry": ch.expiry, "T": T, "atm_iv": _atm_iv(ch, F, T, SETTINGS.risk_free_rate)})
    return rows
