"""Shared cell→verdict aggregation — the one place a bag of resolved-tip outcomes becomes per-cell
``TipValidationReport`` rows (with the full anti-overfitting battery).

Both the OPTION tip backtest (``tip_backtest``), the single-stock EQUITY backtest (``tips.equities``)
and the live RE-validation job (``backtest.revalidate``) feed the same ``cells`` shape here, so the
gate's evidence is computed identically no matter which engine produced the tips:

    cells[(structure, regime_bucket, underlying)] = {
        "returns": [per-trade post-cost return on risk],
        "net":     [per-trade net ₹ P&L],
        "conv":    [stated conviction],
        "wins":    int,                      # count of net>0
        "by_day":  {resolution_day_iso: [returns…]},
    }

Headline-eligibility is the conjunction of: sample size, calibration (realized win-rate ≥ mean stated
conviction), positive post-cost edge, Harvey t≥3, Deflated Sharpe ≥ 0.95, global PBO ≤ 0.5, a positive
bootstrap 5th-percentile edge, a positive walk-forward OUT-OF-FOLD edge, AND a positive MEDIAN
combinatorial-purged-CV edge (``combinatorial_purged_splits`` is now exercised in certification, not just
defined). Both OOF checks purge an ``embargo`` ≥ the label horizon (threaded by the caller). All of these
run on DAY-BLOCKED returns (one statistic per independent trading day). The gate only ever READS this
verdict.
"""

from __future__ import annotations

import warnings

import numpy as np

from ..tips.store import GATE_VERSION, TipValidationReport
from . import validation as val
from .robustness import block_bootstrap_edge

DSR_PASS = 0.95
PBO_MAX = 0.5
# Conservative cross-trial Sharpe variance (σ≈0.5) used ONLY when a cell is the sole member of its
# structure family, so the Deflated Sharpe still deflates it for multiple testing instead of riding the
# optimistically-tiny 1/(n-1) single-Sharpe sampling variance (which would over-certify a lone cell).
_SINGLETON_SR_VARIANCE = 0.25


def global_pbo(cells: dict, res_days: list[str]) -> float:
    """Probability of Backtest Overfitting across cells (configs) over resolution days (periods).
    NaN when there isn't enough structure to compute it (treated as a fail by the gate)."""
    keys = sorted(cells.keys())
    if len(keys) < 2 or len(res_days) < 4:
        return float("nan")
    M = np.full((len(res_days), len(keys)), np.nan)
    for j, ck in enumerate(keys):
        by_day = cells[ck]["by_day"]
        for i, d in enumerate(res_days):
            vals = by_day.get(d)
            if vals:
                M[i, j] = float(np.mean(vals))
    n_splits = min(8, len(res_days))
    n_splits -= n_splits % 2
    if n_splits < 2:
        return float("nan")
    # Sparse per-symbol cells leave all-NaN CSCV blocks → benign nanmean/DOF warnings; silence them.
    with warnings.catch_warnings(), np.errstate(invalid="ignore", divide="ignore"):
        warnings.simplefilter("ignore", RuntimeWarning)
        return val.probability_of_backtest_overfitting(M, n_splits=n_splits)


def _day_blocked_returns(cell: dict) -> list[float]:
    """Collapse a cell to ONE return per INDEPENDENT trading day (effective-n = independent days).

    Same-day tips are correlated (every upside strike resolves together on a jump day; the whole
    cross-section moves together on a market day), so counting them as independent observations
    inflates t = SR*sqrt(n) and the Deflated Sharpe. Averaging each day's per-trade returns into a
    single day return makes significance track independent days — what ``cell_from_daily`` already
    does for the touch curve, now applied uniformly so the OPTION and EQUITY gates can no longer
    certify clustering. Falls back to raw per-trade returns only when a cell carries no ``by_day``."""
    by_day = cell.get("by_day") or {}
    if by_day:
        return [float(np.mean(v)) for _, v in sorted(by_day.items()) if len(v)]
    return [float(x) for x in cell.get("returns", [])]


def cpcv_oof_edge(day_returns, *, embargo: int = 5, n_splits: int = 5) -> float:
    """Mean OUT-OF-FOLD edge across embargoed walk-forward splits — does the cell's edge HOLD on the
    forward (out-of-sample) blocks, or did it all accrue in the first window the gate only ever trains on?

    ``combinatorial_purged_splits`` / ``purged_walk_forward_splits`` existed but were never called in
    certification — leak-safety rested on ``AsOfContext`` alone. ``purged_walk_forward_splits`` trains on
    the past and tests each forward block, purging an ``embargo`` (≥ the cell's label horizon, threaded
    in by the caller) so a multi-day label can't leak train↔test. Returns the mean of the forward folds'
    mean returns; eligibility requires it ``> 0``. A cell whose positive grand mean came from one
    contiguous early block fails, because that block is train-only and the forward folds don't hold it.
    NaN when there are too few independent days to split (treated as a fail by the gate)."""
    r = np.asarray(list(day_returns), dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < n_splits:
        return float("nan")
    splits = val.purged_walk_forward_splits(n, n_splits=n_splits, embargo=max(0, int(embargo)))
    fold_edges = [float(r[test].mean()) for _train, test in splits if len(test)]
    if not fold_edges:
        return float("nan")
    return float(np.mean(fold_edges))


def cpcv_oof_edge_combinatorial(day_returns, *, embargo: int = 5, n_groups: int = 6,
                                n_test_groups: int = 2) -> float:
    """MEDIAN out-of-sample edge across COMBINATORIAL purged splits — a stricter companion to the
    walk-forward ``cpcv_oof_edge``. ``combinatorial_purged_splits`` partitions the independent days into
    ``n_groups`` contiguous groups and holds out every C(n_groups, n_test_groups) combination as the test
    set (≈15 paths for 6-choose-2), purging an ``embargo`` (≥ the label horizon, threaded by the caller)
    around each so a multi-day label can't leak. We return the MEDIAN of the held-out path edges — NOT the
    mean, which (because every group sits in the test set equally often) collapses to the grand mean and
    would merely restate ``edge>0``. An edge concentrated in one window survives only the few paths that
    test that window, so a MAJORITY of paths come out negative and the median falls ≤0; eligibility
    requires it ``>0``, i.e. the edge must hold across most held-out combinations, not just the forward
    folds. ``combinatorial_purged_splits`` was DEFINED in ``validation`` but never called in certification
    — this wires it in. NaN when there are too few independent days to form the groups (a fail by the gate)."""
    r = np.asarray(list(day_returns), dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < n_groups:
        return float("nan")
    splits = val.combinatorial_purged_splits(
        n, n_groups=n_groups, n_test_groups=n_test_groups, embargo=max(0, int(embargo)))
    fold_edges = [float(r[test].mean()) for _train, test in splits if len(test)]
    if not fold_edges:
        return float("nan")
    return float(np.median(fold_edges))


def validate_cells(
    cells: dict, res_days: list[str], *, min_samples: int, updated_ts: str = "",
    bootstrap_seed: int = 0, n_trials: int | None = None, embargo: int = 5,
    model_version: str = GATE_VERSION,
) -> tuple[list[TipValidationReport], float]:
    """Turn aggregated ``cells`` into per-cell ``TipValidationReport``s + the global PBO.

    Significance is computed on DAY-BLOCKED returns (one statistic per independent trading day), so
    correlated same-day tips cannot inflate the t-stat / Deflated Sharpe on ANY engine (the option &
    equity gates previously fed per-trade n here — the clustering hole). The Deflated Sharpe discounts
    for the number of trials actually run against this data: ``max(len(cells), n_trials)`` — pass
    ``n_trials`` from the experiment/trial registry so a tuned threshold/target/horizon raises the bar
    instead of sneaking through (``len(cells)`` alone never counts the researcher's search). The
    Deflated Sharpe's variance is taken WITHIN a structure family (a lone-member family falls back to a
    conservative cross-trial variance, never the optimistic 1/(n-1)); eligibility now also requires a
    positive walk-forward OUT-OF-FOLD edge (``embargo`` ≥ the label horizon, threaded by the caller);
    and each verdict is stamped with ``model_version`` so a stale green can be demoted by the gate.
    Returns ``(reports, global_pbo)``; the caller upserts."""
    res_days = sorted(res_days)
    pbo = global_pbo(cells, res_days)
    day_rets = {ck: _day_blocked_returns(c) for ck, c in cells.items()}
    sharpes = {ck: val.sharpe_ratio(r) for ck, r in day_rets.items()}
    # Per-FAMILY Sharpe spread feeds the Deflated Sharpe's variance — don't pool unrelated structures
    # (an option strangle and an equity-momentum cell are different bets, so their Sharpe dispersion
    # shouldn't cross-contaminate the deflation). Family = the structure key.
    fam_sr: dict[str, list[float]] = {}
    for (structure, _b, _u), s in sharpes.items():
        if s == s:
            fam_sr.setdefault(structure, []).append(s)
    # Honest multiple-testing count: never fewer than the configs actually tried against this data.
    effective_trials = max(len(cells), int(n_trials or 0), 1)

    reports: list[TipValidationReport] = []
    for ck, c in cells.items():
        structure, bucket, u = ck
        rets = day_rets[ck]
        n = len(rets)
        wins = sum(1 for r in rets if r > 0)
        win_rate = wins / n if n else float("nan")
        mean_conv = float(np.mean(c["conv"])) if c["conv"] else float("nan")
        mean_net = float(np.mean(c["net"])) if c["net"] else float("nan")
        edge = float(np.mean(rets)) if n else float("nan")  # post-cost per-DAY return on risk
        sr = sharpes[ck]
        t = val.t_stat(rets)
        if n >= 2 and sr == sr:
            fam = [s for s in fam_sr.get(structure, []) if s == s]
            # Within-family Sharpe dispersion (multi-member); a lone-member family falls back to a
            # CONSERVATIVE cross-trial variance — never the optimistic 1/(n-1) single-Sharpe variance.
            sr_var = max(float(np.var(fam, ddof=1)), 1e-9) if len(fam) > 1 else _SINGLETON_SR_VARIANCE
            dsr = val.deflated_sharpe_ratio(sr, n_trials=effective_trials, n_obs=n, sr_variance=sr_var)
        else:
            dsr = float("nan")
        boot = block_bootstrap_edge(rets, seed=bootstrap_seed)
        p_low = boot["p_low"]
        cpcv = cpcv_oof_edge(rets, embargo=embargo)  # edge must HOLD out-of-fold (walk-forward), not in-sample
        cpcv_c = cpcv_oof_edge_combinatorial(rets, embargo=embargo)  # ...and across a MAJORITY of CPCV paths
        eligible = bool(
            n >= min_samples
            and win_rate == win_rate and mean_conv == mean_conv and win_rate >= mean_conv
            and edge > 0
            and val.passes_t_hurdle(t)
            and dsr == dsr and dsr >= DSR_PASS
            and pbo == pbo and pbo <= PBO_MAX
            and p_low == p_low and p_low > 0
            and cpcv == cpcv and cpcv > 0
            and cpcv_c == cpcv_c and cpcv_c > 0
        )
        reports.append(TipValidationReport(
            structure=structure, regime_bucket=bucket, underlying=u, n=n,
            win_rate=round(win_rate, 4) if win_rate == win_rate else float("nan"),
            mean_conviction=round(mean_conv, 4) if mean_conv == mean_conv else float("nan"),
            mean_net_pnl=round(mean_net, 2) if mean_net == mean_net else float("nan"),
            cost_adjusted_edge=round(edge, 6) if edge == edge else float("nan"),
            t_stat=round(t, 4) if t == t else float("nan"),
            dsr=round(dsr, 4) if dsr == dsr else float("nan"),
            pbo=round(pbo, 4) if pbo == pbo else float("nan"),
            robustness_p_low=round(p_low, 6) if p_low == p_low else float("nan"),
            headline_eligible=eligible, updated_ts=updated_ts, model_version=model_version,
        ))
    return reports, pbo


def new_cell() -> dict:
    """A fresh empty cell accumulator (use with ``collections.defaultdict``)."""
    from collections import defaultdict
    return {"returns": [], "net": [], "conv": [], "wins": 0, "by_day": defaultdict(list)}


def cell_from_daily(daily, *, conviction: float | None = None) -> dict:
    """Build a ``validate_cells`` cell from DAY-LEVEL outcomes (C3). ``daily`` = iterable of
    ``(day_iso, day_return[, win])``; ``win`` defaults to ``day_return > 0``. Collapses each day to a
    single statistic so the gate's effective-n tracks INDEPENDENT trading days."""
    cell = new_cell()
    for rec in daily:
        day, ret = rec[0], float(rec[1])
        win = int(rec[2]) if len(rec) > 2 else int(ret > 0)
        cell["returns"].append(ret)
        cell["net"].append(ret)
        cell["conv"].append(float(conviction) if conviction is not None else 0.5)
        cell["wins"] += win
        cell["by_day"][day].append(ret)
    return cell
