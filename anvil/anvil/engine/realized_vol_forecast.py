"""Realized-vol FORECAST + the variance-risk-premium (VRP) read — the environment gate's "is buying
premium even +EV right now?" signal.

Pure numpy, no GARCH (``arch`` has no py3.14 wheel). Two honesty-driven choices:
  * **Range-based RV (Garman-Klass / Parkinson, C4)** from the OHLC we already fetch for touch
    resolution — several× more statistically efficient than close-to-close for the same sample.
  * VRP is recorded as a **resolvable PROBABILITY (C7)**: ``P(realized vol over the horizon < implied
    vol)`` — i.e. "the premium turns out to have been rich." The raw spread ``IV − E[RV]`` is display
    context only. The IV tenor must be **horizon-matched** to the RV-forecast horizon (C5).

The realized-vol forecast is HAR-RV (heterogeneous autoregressive: daily/weekly/monthly components)
with an EWMA / trailing fallback when history is thin.
"""

from __future__ import annotations

import math

import numpy as np

_ANN = 252.0
_GK_C = 2.0 * math.log(2.0) - 1.0  # Garman-Klass cross term coefficient


def _ohlc_arrays(ohlc):
    """Accept a list of (o,h,l,c) tuples/dicts → four float arrays. Drops non-positive rows."""
    o, h, lo, c = [], [], [], []
    for row in ohlc or []:
        if isinstance(row, dict):
            vo, vh, vl, vc = row.get("o"), row.get("h"), row.get("l"), row.get("c")
        else:
            vo, vh, vl, vc = (list(row) + [None, None, None, None])[:4]
        try:
            vo, vh, vl, vc = float(vo), float(vh), float(vl), float(vc)
        except (TypeError, ValueError):
            continue
        if min(vo, vh, vl, vc) > 0 and vh >= vl:
            o.append(vo)
            h.append(vh)
            lo.append(vl)
            c.append(vc)
    return np.array(o), np.array(h), np.array(lo), np.array(c)


def gk_daily_variance(ohlc) -> np.ndarray:
    """Per-day Garman-Klass variance estimate: 0.5·(ln H/L)² − (2ln2−1)·(ln C/O)² (C4)."""
    o, h, lo, c = _ohlc_arrays(ohlc)
    if o.size == 0:
        return np.array([])
    hl = np.log(h / lo) ** 2
    co = np.log(c / o) ** 2
    return np.maximum(0.5 * hl - _GK_C * co, 1e-12)


def parkinson_daily_variance(ohlc) -> np.ndarray:
    """Per-day Parkinson variance: (ln H/L)² / (4 ln 2). Simpler range estimator (C4 fallback)."""
    _o, h, lo, _c = _ohlc_arrays(ohlc)
    if h.size == 0:
        return np.array([])
    return np.maximum(np.log(h / lo) ** 2 / (4.0 * math.log(2.0)), 1e-12)


def realized_vol_gk(ohlc, *, annualize: int = _ANN) -> float | None:
    """Whole-window annualized realized vol from the Garman-Klass daily variances."""
    v = gk_daily_variance(ohlc)
    if v.size == 0:
        return None
    return float(np.sqrt(v.mean() * annualize))


def ewma_vol_forecast(ohlc, *, lam: float = 0.94, annualize: int = _ANN) -> float | None:
    """RiskMetrics EWMA of the GK daily variances → annualized vol forecast."""
    v = gk_daily_variance(ohlc)
    if v.size == 0:
        return None
    w = (1 - lam) * lam ** np.arange(v.size)[::-1]
    ewma_var = float(np.sum(w * v) / np.sum(w))
    return float(np.sqrt(ewma_var * annualize))


def har_rv_forecast(ohlc, horizon: int = 5, *, annualize: int = _ANN) -> dict:
    """HAR-RV forecast of annualized realized vol over the next ``horizon`` trading days (C5).

    Regresses the realized variance over the forward horizon on the daily / weekly(5) / monthly(22)
    average daily variance (point-in-time; features at t, target over t+1..t+h), pure-numpy lstsq.
    Falls back to EWMA, then trailing GK, when history is thin. Returns
    ``{e_rv, method, n, log_rv_std, horizon}`` — ``log_rv_std`` is the std of log rolling-RV (the
    dispersion the VRP probability uses)."""
    v = gk_daily_variance(ohlc)  # daily variance series
    n = int(v.size)
    horizon = int(max(1, horizon))
    # log-RV dispersion from a rolling-horizon RV series (for the VRP probability's spread).
    log_rv_std = 0.45
    if n > horizon + 5:
        roll = np.array([np.sqrt(v[i:i + horizon].mean() * annualize) for i in range(n - horizon)])
        roll = roll[roll > 0]
        if roll.size > 2:
            log_rv_std = float(np.std(np.log(roll), ddof=1)) or 0.45

    # HAR needs ~22 (monthly) + horizon + a handful of samples.
    if n >= 22 + horizon + 8:
        d = v
        w = np.array([v[max(0, i - 4):i + 1].mean() for i in range(n)])
        m = np.array([v[max(0, i - 21):i + 1].mean() for i in range(n)])
        lo, hi = 22, n - horizon  # rows with full features AND a full forward target
        y = np.array([v[i + 1:i + 1 + horizon].mean() for i in range(lo, hi)])
        X = np.column_stack([np.ones(hi - lo), d[lo:hi], w[lo:hi], m[lo:hi]])
        if X.shape[0] >= 8:
            coef, *_ = np.linalg.lstsq(X, y, rcond=None)
            x_now = np.array([1.0, d[-1], w[-1], m[-1]])
            e_var = float(max(np.dot(coef, x_now), 1e-12))
            return {"e_rv": float(np.sqrt(e_var * annualize)), "method": "har_rv",
                    "n": n, "log_rv_std": log_rv_std, "horizon": horizon}

    ewma = ewma_vol_forecast(ohlc, annualize=annualize)
    if ewma is not None:
        return {"e_rv": ewma, "method": "ewma", "n": n, "log_rv_std": log_rv_std, "horizon": horizon}
    rv = realized_vol_gk(ohlc, annualize=annualize)
    return {"e_rv": rv, "method": "trailing_gk" if rv else "none", "n": n,
            "log_rv_std": log_rv_std, "horizon": horizon}


def vrp(atm_iv: float | None, e_rv: float | None, *, log_rv_std: float = 0.45,
        horizon: int = 5) -> dict:
    """The VRP read as a RESOLVABLE PROBABILITY (C7).

    ``vrp = atm_iv − e_rv`` (display only). The calibratable object is
    ``prob_realized_lt_implied = P(RV_horizon < IV)`` modeling log-RV ~ Normal(log E[RV], log_rv_std):
    ``Φ((ln IV − ln E[RV]) / log_rv_std)``. High prob ⇒ premium likely rich ⇒ buying unfavorable.
    ``richness`` ∈ {rich, fair, cheap} buckets the spread for the environment band."""
    if not atm_iv or atm_iv <= 0 or not e_rv or e_rv <= 0:
        return {"vrp": None, "prob_realized_lt_implied": None, "richness": "unknown",
                "atm_iv": atm_iv, "e_rv": e_rv, "horizon": horizon}
    spread = float(atm_iv - e_rv)
    sd = max(0.05, float(log_rv_std))
    z = (math.log(atm_iv) - math.log(e_rv)) / sd
    prob = float(0.5 * (1.0 + math.erf(z / math.sqrt(2.0))))  # Φ(z)
    rel = spread / atm_iv
    richness = "rich" if rel > 0.10 else "cheap" if rel < -0.05 else "fair"
    return {"vrp": round(spread, 4), "prob_realized_lt_implied": round(prob, 4),
            "richness": richness, "atm_iv": round(float(atm_iv), 4), "e_rv": round(float(e_rv), 4),
            "rel": round(rel, 4), "horizon": int(horizon)}


def vrp_ratio_for_touch(atm_iv: float | None, e_rv: float | None) -> float | None:
    """The LIVE physical-touch scaler ``forecast_RV / ATM_IV`` (C2) — None when either is missing."""
    if not atm_iv or atm_iv <= 0 or not e_rv or e_rv <= 0:
        return None
    return float(e_rv / atm_iv)
