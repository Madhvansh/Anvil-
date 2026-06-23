"""Probability-of-touch (first-passage) — the buyer's actual question: will spot TAG strike K at any
time within horizon T (not just finish beyond it at expiry)?

Honest by construction:
  * Monte-Carlo GBM paths at the option-IMPLIED vol on the risk-neutral forward, with the closed-form
    BROWNIAN-BRIDGE crossing correction between daily nodes (Beaglehole-Dybvig-Zhou) so we don't
    under-count intraday breach-and-return — the classic discrete-monitoring bias (C1). Without it a
    daily-node check is biased LOW exactly near strikes / short horizons (the buyer's zone).
  * Risk-neutral P(touch) OVERSTATES real-world touch (implied vol > realized on average), so we also
    report a VRP-ADJUSTED PHYSICAL read scaling vol by a LIVE realized/implied ratio (C2). The
    adjustment is VOL-ONLY — it ignores the small physical drift change, which is fine for short
    horizons where vol dominates touch; revisit for long horizons (C14).
  * ONE shared path ensemble (shared standard-normal draws) is reused across every strike AND across
    the risk-neutral/physical reads (C13) — no per-strike re-simulation.

Pure numpy. The reflection-principle identity ``P(touch B) ≈ 2·P(terminal beyond B)`` for a driftless
ATM-forward barrier is the tight unit-test the bridge correction must pass.
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS

_TRADING_DAYS = 252.0


def _increments(n_paths: int, horizon_days: int, seed: int) -> tuple[np.ndarray, float]:
    """Standard-normal step increments drawn ONCE (shape (n_paths, n_steps)) + dt. Both the
    risk-neutral and physical paths are built from these same draws (C13)."""
    n_steps = int(max(1, round(horizon_days)))
    dt = 1.0 / _TRADING_DAYS
    rng = np.random.default_rng(int(seed))
    return rng.standard_normal((n_paths, n_steps)), dt


def _logpaths(s0: float, sigma: float, r: float, q: float, z: np.ndarray, dt: float) -> np.ndarray:
    """Log-price node paths from shared draws ``z`` at vol ``sigma``. Shape (n_paths, n_steps+1)."""
    drift = (r - q - 0.5 * sigma * sigma) * dt
    incr = drift + sigma * np.sqrt(dt) * z
    cum = np.cumsum(incr, axis=1)
    zero = np.zeros((z.shape[0], 1))
    return np.log(s0) + np.concatenate([zero, cum], axis=1)


def _p_touch(logS: np.ndarray, K: float, sigma: float, dt: float, *, upside: bool) -> float:
    """Bridge-corrected P(touch barrier K) given log-price node paths (C1).

    Between consecutive nodes (both on the un-breached side of the barrier) the probability the
    continuous bridge crossed the log-barrier ``b`` is ``exp(-2·(b-xᵢ)·(b-xᵢ₊₁)/v)`` for an upper
    barrier (mirror for a lower one), with per-step log-variance ``v = σ²·dt``. Any node already at/
    beyond the barrier crosses with probability 1."""
    logB = float(np.log(K))
    v = sigma * sigma * dt
    if v <= 0:  # degenerate: touch iff some node crosses
        ext = logS.max(axis=1) if upside else logS.min(axis=1)
        return float((ext >= logB).mean() if upside else (ext <= logB).mean())
    lo, hi = logS[:, :-1], logS[:, 1:]
    if upside:
        a, c = logB - lo, logB - hi
        crossed = (lo >= logB) | (hi >= logB)
    else:
        a, c = lo - logB, hi - logB
        crossed = (lo <= logB) | (hi <= logB)
    with np.errstate(over="ignore", invalid="ignore"):
        p_step = np.exp(-2.0 * a * c / v)
    p_step = np.where(crossed, 1.0, p_step)
    p_step = np.clip(np.nan_to_num(p_step, nan=1.0), 0.0, 1.0)
    p_no_touch = np.prod(1.0 - p_step, axis=1)
    return float(1.0 - p_no_touch.mean())


def touch_probabilities(
    spot: float,
    atm_iv: float | None,
    horizon_days: int,
    strikes,
    *,
    r: float | None = None,
    q: float | None = None,
    vrp_ratio: float | None = None,
    n_paths: int = 10000,
    seed: int = 0,
) -> dict:
    """``{K: {strike, dir, p_touch_rn, p_touch_phys, vrp_ratio, vrp_ratio_fallback}}`` per strike.

    ``atm_iv`` (annualized) is the path vol — front-month ATM by default (C12); per-strike smile IV is
    a later refinement. ``vrp_ratio = forecast_RV/ATM_IV`` (C2) scales vol for the PHYSICAL read; when
    None it falls back to ``SETTINGS.paper_vrp_ratio`` (flagged ``vrp_ratio_fallback=True`` so
    calibration can separate the two regimes)."""
    if not atm_iv or atm_iv <= 0 or spot <= 0 or not list(strikes):
        return {}
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    used_fallback = vrp_ratio is None
    ratio = max(0.1, min(2.0, float(vrp_ratio) if vrp_ratio is not None else float(SETTINGS.paper_vrp_ratio)))
    sigma_phys = atm_iv * ratio

    z, dt = _increments(n_paths, horizon_days, seed)
    logS_rn = _logpaths(spot, atm_iv, r, q, z, dt)
    logS_ph = _logpaths(spot, sigma_phys, r, q, z, dt)

    out: dict[float, dict] = {}
    for k in strikes:
        k = float(k)
        if k <= 0:
            continue
        up = k >= spot
        out[k] = {
            "strike": k,
            "dir": "up" if up else "down",
            "p_touch_rn": round(_p_touch(logS_rn, k, atm_iv, dt, upside=up), 4),
            "p_touch_phys": round(_p_touch(logS_ph, k, sigma_phys, dt, upside=up), 4),
            "vrp_ratio": round(ratio, 4),
            "vrp_ratio_fallback": used_fallback,
        }
    return out


def touch_for_dist(dist, horizon_days: int, *, strikes=None, vrp_ratio: float | None = None,
                   n_paths: int = 10000, seed: int = 0) -> dict:
    """Convenience: probabilities for a built ``ImpliedDistribution``. Default strikes are spot and a
    grid at ±0.5σ/±1σ/±1.5σ/±2σ (the levels a buyer actually weighs)."""
    if dist is None or not getattr(dist, "atm_iv", None):
        return {}
    spot = float(dist.spot)
    em = float(dist.expected_move_1sigma or 0.0)
    if strikes is None:
        mults = (-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0)
        strikes = [spot + m * em for m in mults] if em > 0 else [spot]
    return touch_probabilities(spot, dist.atm_iv, horizon_days, strikes,
                               vrp_ratio=vrp_ratio, n_paths=n_paths, seed=seed)
