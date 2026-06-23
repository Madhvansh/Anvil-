"""Chain-DYNAMICS analytics (Wave 3) — read the option chain as a *shape* and, when a prior chain or a
recorded series is supplied, as a *time-derivative*. Pure-numpy, chain-only except where history is
passed (then it abstains cleanly). Extends — does not duplicate — the existing primitives:

- **iv_skew_slope** — the FITTED smile (IV vs log-moneyness slope + curvature), richer than the 2-point
  ``engine.vol.skew`` risk-reversal.
- **oi_change_bias** — net directional bias from per-strike OI *change* (the dynamic behind PCR-OI).
- **smart_money_blocks** — cross-sectional volume z-score outliers (unusual large activity / "blocks").
- **zero_dte_dynamics** — expiry-proximity pin dynamics (DTE flags + max-pain pull).
- **max_pain_drift** — migration of max-pain over recorded snapshots (positioning shifting up/down).

Honesty: shape/dynamics reads return slopes/agreement numbers, never an accuracy %; block detection is
noisy (CONFIRMATION). Every reader returns None / a not-fired dict on insufficient data.
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from . import greeks as gk
from .forward import resolve_forward
from .oi import max_pain
from .util import year_fraction


def _row_iv(row, F: float, T: float, r: float) -> float | None:
    if row is None:
        return None
    iv = row.iv
    if (iv is None or iv <= 0) and row.ltp:
        iv = gk.implied_vol(row.ltp, row.option_type, F, row.strike, T, r)
    return float(iv) if (iv and iv == iv and iv > 0) else None


def iv_skew_slope(chain: OptionChain, r: float | None = None, q: float | None = None) -> dict | None:
    """Fit IV vs log-moneyness ``ln(K/F)`` across OTM strikes → linear ``slope`` (negative = the usual
    equity fear skew, OTM puts richer) + ``curvature`` (smile convexity) + ``atm_iv`` (fit at K=F).
    None if < 3 usable points."""
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
    F, _ = resolve_forward(chain, r, q)
    if F <= 0:
        return None
    xs: list[float] = []
    ys: list[float] = []
    for row in chain.rows:
        otm = ((row.option_type == OptionType.PUT and row.strike <= F)
               or (row.option_type == OptionType.CALL and row.strike >= F))
        if not otm:
            continue
        iv = _row_iv(row, F, T, r)
        if iv is None:
            continue
        xs.append(float(np.log(row.strike / F)))
        ys.append(iv)
    if len(xs) < 3:
        return None
    x = np.asarray(xs)
    y = np.asarray(ys)
    a = np.vstack([np.ones_like(x), x, x * x]).T
    coef, *_ = np.linalg.lstsq(a, y, rcond=None)
    c0, slope, curv = (float(c) for c in coef)
    return {"slope": slope, "curvature": curv, "atm_iv": float(c0), "n": len(xs)}


def oi_change_bias(chain: OptionChain, prev_chain: OptionChain | None = None) -> dict | None:
    """Net directional bias from per-strike OI CHANGE. Uses ``row.oi_change`` if present, else diffs vs
    ``prev_chain``. Convention (writing view): fresh PUT OI building = support = bullish; fresh CALL OI
    building = resistance = bearish → ``net = (put_build - call_build)/total``. None if no OI-change data."""
    prev_map: dict = {}
    if prev_chain is not None:
        for pr in prev_chain.rows:
            prev_map[(pr.strike, pr.option_type)] = pr.oi or 0.0
    call_build = put_build = 0.0
    have = False
    for row in chain.rows:
        dc = row.oi_change
        if (dc is None or dc == 0) and prev_chain is not None:
            dc = (row.oi or 0.0) - prev_map.get((row.strike, row.option_type), 0.0)
        if dc is None:
            continue
        have = True
        if row.option_type == OptionType.CALL:
            call_build += dc
        else:
            put_build += dc
    if not have:
        return None
    total = abs(call_build) + abs(put_build)
    if total <= 0:
        return {"call_build": call_build, "put_build": put_build, "net": 0.0, "bias": "neutral", "strength": 0.0}
    net = (put_build - call_build) / total
    bias = "bullish" if net > 0 else ("bearish" if net < 0 else "neutral")
    return {"call_build": call_build, "put_build": put_build, "net": float(net),
            "bias": bias, "strength": float(min(1.0, abs(net)))}


def smart_money_blocks(chain: OptionChain, z_threshold: float = 2.5) -> dict | None:
    """Cross-sectional volume anomaly: strikes whose volume is a z-score outlier vs the chain's volume
    distribution = unusually large activity ("blocks"), with a net call/put tilt. None if < 5 strikes
    or zero dispersion. Noisy → callers tier CONFIRMATION."""
    meta = [(row.strike, row.option_type, float(row.volume or 0.0)) for row in chain.rows]
    if len(meta) < 5:
        return None
    vols = np.asarray([v for *_, v in meta], dtype=float)
    mu = float(vols.mean())
    sd = float(vols.std())
    if sd <= 0:
        return None
    blocks: list[dict] = []
    call_v = put_v = 0.0
    for k, t, v in meta:
        z = (v - mu) / sd
        if z >= z_threshold:
            blocks.append({"strike": k, "type": t.value, "volume": v, "z": float(z)})
            if t == OptionType.CALL:
                call_v += v
            else:
                put_v += v
    if not blocks:
        return {"blocks": [], "tilt": "neutral", "n_blocks": 0}
    tilt = "call_heavy" if call_v > put_v else ("put_heavy" if put_v > call_v else "balanced")
    return {"blocks": blocks, "n_blocks": len(blocks), "tilt": tilt,
            "call_volume": call_v, "put_volume": put_v}


def zero_dte_dynamics(chain: OptionChain, T: float | None = None) -> dict:
    """Expiry-proximity pin dynamics (chain-only): DTE, 0DTE / expiry-week flags, max-pain + spot's
    fractional distance to it (the pin pull). Always returns a dict."""
    if T is None:
        T = max(year_fraction(chain.expiry, chain.timestamp), 1e-6)
    dte = float(T) * 365.0
    mp = max_pain(chain)
    spot = float(chain.spot)
    pin_dist = abs(spot - mp) / spot if (mp and spot > 0) else None
    return {"dte": dte, "is_0dte": dte <= 1.0, "is_expiry_week": dte <= 5.0,
            "max_pain": mp, "pin_distance": pin_dist}


def max_pain_drift(max_pain_series) -> dict | None:
    """Migration of max-pain over recorded snapshots (pin moving up/down = positioning shifting). None if
    < 2 points."""
    s = [float(x) for x in (max_pain_series or []) if x is not None]
    if len(s) < 2:
        return None
    drift = s[-1] - s[0]
    direction = "up" if drift > 0 else ("down" if drift < 0 else "flat")
    return {"drift": float(drift), "direction": direction, "first": s[0], "last": s[-1], "n": len(s)}
