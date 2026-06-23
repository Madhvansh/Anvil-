"""Validation science — the anti-overfitting spine that gates which signals may mint *headline*
tips. Pure functions over arrays; no I/O, no market specifics.

A backtested win-rate is worthless without these guards, because it is trivial to manufacture a
high in-sample number via overfitting, look-ahead, survivorship, or multiple testing. This module
provides the four defenses the plan mandates:

  * Purged + embargoed cross-validation (López de Prado) — never plain k-fold, so a multi-period
    label horizon cannot leak from train into test;
  * Combinatorial Purged CV (CPCV) — many train/test partitions, not one lucky split;
  * Deflated Sharpe Ratio + Probabilistic Sharpe Ratio (Bailey & López de Prado 2014) — discount the
    observed Sharpe for the number of trials and for non-normal returns;
  * Probability of Backtest Overfitting via Combinatorially Symmetric CV (CSCV) — how often the
    best in-sample config lands in the bottom half out-of-sample;
  * the Harvey, Liu & Zhu (2016) t-stat hurdle of 3.0 (not 2.0) for any new signal.

References: López de Prado, *Advances in Financial Machine Learning* (2018); Bailey & López de
Prado, "The Deflated Sharpe Ratio" (2014); Harvey, Liu & Zhu, "...and the Cross-Section of Expected
Returns" (2016).
"""

from __future__ import annotations

import itertools
import math

import numpy as np
from scipy.stats import norm, rankdata

# Harvey, Liu & Zhu (2016): with hundreds of factors mined, the conventional |t| > 2 is far too
# lenient; |t| >= 3 is the defensible hurdle for declaring a new signal real.
HARVEY_T_HURDLE = 3.0
_EULER_MASCHERONI = 0.5772156649015329


# --------------------------------------------------------------------------- basic stats
def sharpe_ratio(returns) -> float:
    """Per-period Sharpe (mean / std, ddof=1). NOT annualized — annualize downstream if needed."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return float("nan")
    sd = r.std(ddof=1)
    if sd <= 0:
        return float("nan")
    return float(r.mean() / sd)


def t_stat(returns) -> float:
    """t-statistic of the mean return = Sharpe * sqrt(n). The Harvey hurdle is applied to |t|."""
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return float("nan")
    sr = sharpe_ratio(r)
    if not math.isfinite(sr):
        return float("nan")
    return float(sr * math.sqrt(r.size))


def passes_t_hurdle(t_value: float, hurdle: float = HARVEY_T_HURDLE) -> bool:
    """True iff |t| clears the Harvey hurdle (default 3.0)."""
    return bool(math.isfinite(t_value) and abs(t_value) >= hurdle)


# --------------------------------------------------------------------------- Sharpe deflation
def probabilistic_sharpe_ratio(
    observed_sr: float, benchmark_sr: float, n_obs: int, skew: float = 0.0, kurt: float = 3.0
) -> float:
    """PSR: P(true Sharpe > benchmark) given the observed per-period Sharpe, sample size, and the
    return distribution's skew/kurtosis (kurt is NON-excess; normal = 3). Bailey & López de Prado."""
    if n_obs < 2 or not math.isfinite(observed_sr):
        return float("nan")
    var = 1.0 - skew * observed_sr + ((kurt - 1.0) / 4.0) * observed_sr**2
    if var <= 0:
        return float("nan")
    z = (observed_sr - benchmark_sr) * math.sqrt(n_obs - 1) / math.sqrt(var)
    return float(norm.cdf(z))


def expected_max_sharpe_ratio(n_trials: int, sr_variance: float) -> float:
    """E[max Sharpe] across ``n_trials`` independent strategies, given the cross-trial variance of
    the Sharpe estimates. This is the benchmark the Deflated Sharpe must beat. n_trials<=1 → 0
    (no multiple-testing inflation)."""
    if n_trials is None or n_trials <= 1 or sr_variance is None or sr_variance <= 0:
        return 0.0
    sigma = math.sqrt(sr_variance)
    g = _EULER_MASCHERONI
    a = norm.ppf(1.0 - 1.0 / n_trials)
    b = norm.ppf(1.0 - 1.0 / (n_trials * math.e))
    return float(sigma * ((1.0 - g) * a + g * b))


def deflated_sharpe_ratio(
    observed_sr: float,
    n_trials: int,
    n_obs: int,
    sr_variance: float | None = None,
    all_sharpes=None,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """DSR: PSR with the benchmark set to the expected MAXIMUM Sharpe under ``n_trials`` trials —
    i.e. the probability the observed Sharpe survives multiple-testing deflation. In [0,1]; treat
    >= 0.95 as "passes". Provide either ``sr_variance`` or ``all_sharpes`` (the per-trial Sharpes);
    falling back to the H0 variance 1/(n_obs-1) if neither is given."""
    if sr_variance is None:
        if all_sharpes is not None:
            arr = np.asarray(list(all_sharpes), dtype=float)
            arr = arr[np.isfinite(arr)]
            sr_variance = float(arr.var(ddof=1)) if arr.size > 1 else 1.0 / max(n_obs - 1, 1)
        else:
            sr_variance = 1.0 / max(n_obs - 1, 1)
    sr0 = expected_max_sharpe_ratio(n_trials, sr_variance)
    return probabilistic_sharpe_ratio(observed_sr, sr0, n_obs, skew, kurt)


# --------------------------------------------------------------------------- CV split generators
def _contiguous_groups(n_samples: int, n_groups: int) -> list[list[int]]:
    bounds = np.linspace(0, n_samples, n_groups + 1).astype(int)
    return [list(range(int(bounds[i]), int(bounds[i + 1]))) for i in range(n_groups)]


def combinatorial_purged_splits(
    n_samples: int, n_groups: int = 6, n_test_groups: int = 2, embargo: int = 0
) -> list[tuple[list[int], list[int]]]:
    """CPCV: partition the sample into ``n_groups`` contiguous groups, then for every choice of
    ``n_test_groups`` as the test set, return (train_idx, test_idx). Train observations within
    ``embargo`` of ANY test observation are purged (leakage-safe even for non-contiguous test
    groups). Yields C(n_groups, n_test_groups) splits."""
    if n_samples <= 0 or n_test_groups < 1 or n_test_groups >= n_groups:
        return []
    groups = _contiguous_groups(n_samples, n_groups)
    test_arr = np.arange(n_samples)
    out: list[tuple[list[int], list[int]]] = []
    for combo in itertools.combinations(range(n_groups), n_test_groups):
        test_idx = sorted(i for g in combo for i in groups[g])
        if not test_idx:
            continue
        test_set = set(test_idx)
        t = np.asarray(test_idx)
        # train = everything not in test and strictly farther than `embargo` from every test index
        train_idx = [
            i for i in test_arr.tolist()
            if i not in test_set and int(np.abs(t - i).min()) > embargo
        ]
        if train_idx:
            out.append((train_idx, test_idx))
    return out


def purged_walk_forward_splits(
    n_samples: int, n_splits: int = 5, embargo: int = 0
) -> list[tuple[list[int], list[int]]]:
    """Expanding-window walk-forward: each forward block is a test fold; train is everything before
    it minus an ``embargo`` gap (so a label resolving into the gap cannot leak)."""
    if n_samples <= 0 or n_splits < 2:
        return []
    bounds = np.linspace(0, n_samples, n_splits + 1).astype(int)
    out: list[tuple[list[int], list[int]]] = []
    for k in range(1, n_splits):
        test_idx = list(range(int(bounds[k]), int(bounds[k + 1])))
        train_end = int(bounds[k]) - embargo
        train_idx = list(range(0, max(0, train_end)))
        if train_idx and test_idx:
            out.append((train_idx, test_idx))
    return out


# --------------------------------------------------------------------------- PBO via CSCV
def _score_columns(block: np.ndarray) -> np.ndarray:
    """Per-config performance over a block of per-period returns: Sharpe-like mean/std per column.
    Columns with zero variance score by mean alone (so a flat positive series isn't NaN)."""
    mean = np.nanmean(block, axis=0)
    sd = np.nanstd(block, axis=0, ddof=1) if block.shape[0] > 1 else np.zeros(block.shape[1])
    with np.errstate(divide="ignore", invalid="ignore"):
        sr = np.where(sd > 0, mean / sd, mean)
    return sr


def probability_of_backtest_overfitting(perf_matrix, n_splits: int = 8) -> float:
    """PBO via Combinatorially Symmetric CV (Bailey, Borwein, López de Prado, Zhu 2017).

    ``perf_matrix`` is shape (T_periods, N_configs) of per-period performance for N candidate
    configs. Split the T rows into ``n_splits`` (even) contiguous blocks; for every way to take
    half the blocks as in-sample (rest out-of-sample), find the best-IS config and record the logit
    of its OOS relative rank. PBO = fraction of partitions where the IS winner lands in the bottom
    half OOS (logit < 0). High PBO ⇒ the selection is overfit. Returns NaN if input is too small.
    """
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2:
        return float("nan")
    T, N = M.shape
    if N < 2 or n_splits < 2 or n_splits % 2 != 0 or T < n_splits:
        return float("nan")
    bounds = np.linspace(0, T, n_splits + 1).astype(int)
    blocks = [M[int(bounds[i]):int(bounds[i + 1])] for i in range(n_splits)]
    half = n_splits // 2
    logits: list[float] = []
    for is_combo in itertools.combinations(range(n_splits), half):
        is_set = set(is_combo)
        IS = np.vstack([blocks[i] for i in is_combo])
        OOS = np.vstack([blocks[i] for i in range(n_splits) if i not in is_set])
        is_perf = _score_columns(IS)
        oos_perf = _score_columns(OOS)
        if not np.any(np.isfinite(is_perf)):
            continue
        n_star = int(np.nanargmax(np.where(np.isfinite(is_perf), is_perf, -np.inf)))
        ranks = rankdata(np.nan_to_num(oos_perf, nan=-np.inf))  # ascending; high = better OOS
        omega = ranks[n_star] / (N + 1.0)
        omega = min(max(omega, 1e-6), 1.0 - 1e-6)
        logits.append(math.log(omega / (1.0 - omega)))
    if not logits:
        return float("nan")
    return float(np.mean(np.asarray(logits) < 0.0))
