"""Selective prediction — the abstain threshold, set from MEASURED coverage, not a magic constant.

Two pieces:

  * ``risk_coverage_threshold`` (the accuracy knob): instead of a fixed nominal coverage, pick the
    operating point ``tau`` on the accuracy-coverage frontier that maximizes ``coverage · max(edge,0)``
    subject to a calibrated-accuracy floor — an EXPECTED-edge-optimal operating point. ``tau`` is
    chosen on TRAIN folds and its coverage/accuracy are REPORTED on TEST folds (so the operating point
    isn't validated on the data that selected it), and the tau-grid size is logged to the
    ``TrialRegistry`` so this threshold sweep raises the multiple-testing bar honestly (Phase-0 rule).
  * ``ev_coverage_threshold`` (the MONEY knob): the same train→test, trial-counted machinery, but the
    objective is realized ``coverage · mean(net-of-cost return)`` — accuracy isn't P&L, so this is the
    operating point that actually maximizes expected per-decision edge and is what Gate-0 sets the cut on.
  * ``AdaptiveConformal`` (ACI): a time-series-adaptive interface for when exchangeability is violated
    (regimes cluster in time). DEFAULT OFF — its asymptotic coverage is meaningless on the current
    handful of clustered, single-regime backtest points; the abstain decision defaults to the simple
    ``p ∈ [tau_lo, tau_hi] → abstain`` band, optionally Mondrian (regime-bucket-conditioned).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

from ..backtest.validation import purged_walk_forward_splits

# Conservative abstain-heavy default when there isn't enough data to measure a frontier.
_CONSERVATIVE_TAU = 0.90
_DEFAULT_GRID = tuple(round(0.50 + 0.01 * i, 4) for i in range(46))  # 0.50 .. 0.95


def _best_tau_on(scores: np.ndarray, events: np.ndarray, grid, accuracy_floor: float):
    """Argmax over the grid of EXPECTED EDGE ``coverage · max(accuracy − accuracy_floor, 0)`` subject
    to the hard constraint ``accuracy ≥ accuracy_floor``. The edge is measured against the breakeven
    floor (NOT ``tau`` — on calibrated probabilities ``accuracy ≈ tau``, so an ``accuracy − tau`` edge
    would collapse to ~0). This trades coverage against win-rate-above-breakeven for an interior
    operating point that maximizes expected P&L."""
    best_tau, best_obj = None, -np.inf
    for tau in grid:
        mask = scores >= tau
        cov = float(mask.mean())
        if cov <= 0.0:
            continue
        acc = float(events[mask].mean())
        if acc < accuracy_floor:
            continue
        obj = cov * max(acc - accuracy_floor, 0.0)
        if obj > best_obj:
            best_obj, best_tau = obj, float(tau)
    return best_tau


def risk_coverage_threshold(scores, events, *, accuracy_floor: float = 0.52, embargo: int = 1,
                            n_splits: int = 5, grid=_DEFAULT_GRID, trial_registry=None,
                            trial_scope: str | None = None) -> dict:
    """Pick ``tau*`` on TRAIN folds (expected-edge-optimal under the accuracy floor) and report its
    coverage/accuracy on TEST folds. Falls back to a conservative wide ``tau`` when too thin to split.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(events, dtype=float)
    n = s.size
    grid = list(grid)
    if trial_registry is not None and trial_scope:
        try:
            trial_registry.bump(trial_scope, len(grid))
        except Exception:  # noqa: BLE001 - trial logging must never sink a fit
            pass

    splits = purged_walk_forward_splits(n, n_splits=int(n_splits), embargo=max(0, int(embargo)))
    if not splits:
        return {"tau": _CONSERVATIVE_TAU, "coverage": None, "accuracy": None,
                "grid_size": len(grid), "n": int(n), "degraded": True}

    taus: list[float] = []
    test_cov: list[float] = []
    test_acc: list[float] = []
    for train, test in splits:
        bt = _best_tau_on(s[train], y[train], grid, accuracy_floor)
        if bt is None:
            bt = float(grid[-1])  # nothing clears the floor → abstain-heavy
        taus.append(bt)
        sm, ym = s[test], y[test]
        m = sm >= bt
        test_cov.append(float(m.mean()))
        test_acc.append(float(ym[m].mean()) if bool(m.any()) else float("nan"))

    # A fold whose act-set is empty contributes NaN accuracy → benign all-NaN nanmean warning; silence.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cov = float(np.nanmean(test_cov)) if test_cov else None
        acc = float(np.nanmean(test_acc)) if test_acc and not np.all(np.isnan(test_acc)) else None
    return {
        "tau": float(np.median(taus)),
        "coverage": cov,
        "accuracy": acc,
        "grid_size": len(grid),
        "n": int(n),
        "degraded": False,
    }


def _best_tau_on_ev(scores: np.ndarray, returns: np.ndarray, grid):
    """Argmax over the grid of EXPECTED P&L per available decision: ``coverage · mean(return | act-set)``
    where ``return`` is the per-trade return on risk, ALREADY NET of cost. Note this equals
    ``sum(return over act-set) / N`` — so it is maximized by acting on exactly the (score-ranked) region
    whose realized return is positive and abstaining where it goes negative. Accuracy is not money;
    THIS is the operating point that maximizes realized edge, which is what should set the abstain cut."""
    best_tau, best_obj = None, -np.inf
    for tau in grid:
        mask = scores >= tau
        cov = float(mask.mean())
        if cov <= 0.0:
            continue
        obj = cov * float(returns[mask].mean())  # = mean per-decision return contribution
        if obj > best_obj:
            best_obj, best_tau = obj, float(tau)
    return best_tau


def ev_coverage_threshold(scores, returns, *, embargo: int = 1, n_splits: int = 5, grid=_DEFAULT_GRID,
                          trial_registry=None, trial_scope: str | None = None) -> dict:
    """EV-at-coverage sibling of ``risk_coverage_threshold``: pick the EV-maximizing ``tau`` on TRAIN
    folds (``coverage · mean(net-of-cost return)``) and report its coverage + realized EV on TEST folds.
    ``returns`` are the per-trade returns on risk already net of round-trip cost. The grid size is logged
    to the ``TrialRegistry`` so this second threshold sweep also raises the multiple-testing bar (Phase-0
    rule). Returns ``{tau, coverage, ev, grid_size, n, degraded}``; ``ev`` is the realized OOF per-trade
    edge of the act-set — the money number the operating point should be chosen on."""
    s = np.asarray(scores, dtype=float)
    g = np.asarray(returns, dtype=float)
    n = s.size
    grid = list(grid)
    if trial_registry is not None and trial_scope:
        try:
            trial_registry.bump(trial_scope, len(grid))
        except Exception:  # noqa: BLE001 - trial logging must never sink a fit
            pass

    splits = purged_walk_forward_splits(n, n_splits=int(n_splits), embargo=max(0, int(embargo)))
    if not splits:
        return {"tau": _CONSERVATIVE_TAU, "coverage": None, "ev": None,
                "grid_size": len(grid), "n": int(n), "degraded": True}

    taus: list[float] = []
    test_cov: list[float] = []
    test_ev: list[float] = []
    for train, test in splits:
        bt = _best_tau_on_ev(s[train], g[train], grid)
        if bt is None:
            bt = float(grid[-1])  # no profitable act-set in train → abstain-heavy
        taus.append(bt)
        sm, gm = s[test], g[test]
        m = sm >= bt
        test_cov.append(float(m.mean()))
        test_ev.append(float(gm[m].mean()) if bool(m.any()) else float("nan"))

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        cov = float(np.nanmean(test_cov)) if test_cov else None
        ev = float(np.nanmean(test_ev)) if test_ev and not np.all(np.isnan(test_ev)) else None
    return {
        "tau": float(np.median(taus)),
        "coverage": cov,
        "ev": ev,
        "grid_size": len(grid),
        "n": int(n),
        "degraded": False,
    }


def mondrian_thresholds(scores, events, regimes, *, accuracy_floor: float = 0.52, embargo: int = 1,
                        n_splits: int = 5, min_group: int = 40, trial_registry=None,
                        trial_scope: str | None = None) -> dict:
    """Per-regime-bucket abstain thresholds (Mondrian conditioning). A bucket with too few samples
    falls back to the global threshold. Always includes a ``__global__`` entry."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(events, dtype=float)
    rb = np.asarray([str(r) for r in regimes])
    glob = risk_coverage_threshold(s, y, accuracy_floor=accuracy_floor, embargo=embargo,
                                   n_splits=n_splits, trial_registry=trial_registry,
                                   trial_scope=trial_scope)
    out: dict = {"__global__": glob}
    for bucket in sorted(set(rb.tolist())):
        if not bucket:
            continue
        m = rb == bucket
        if int(m.sum()) < int(min_group):
            out[bucket] = glob
        else:
            out[bucket] = risk_coverage_threshold(s[m], y[m], accuracy_floor=accuracy_floor,
                                                  embargo=embargo, n_splits=n_splits)
    return out


@dataclass
class AdaptiveConformal:
    """Adaptive Conformal Inference (Gibbs & Candès): ``α_{t+1} = α_t + γ·(α_target − err_t)`` so
    realized coverage tracks ``1−α_target`` in a rolling window even under drift. Built as an
    interface; ``enabled`` defaults False until live data streams (see module docstring)."""

    alpha_target: float = 0.10
    gamma: float = 0.02
    alpha_t: float = 0.10
    enabled: bool = False
    _history: list = field(default_factory=list)

    def update(self, covered: int | bool) -> float:
        """Feed one realized coverage event (1/True = the act-set decision covered the outcome)."""
        err = 0.0 if int(covered) else 1.0
        self.alpha_t = float(min(1.0, max(0.0, self.alpha_t + self.gamma * (self.alpha_target - err))))
        self._history.append(err)
        return self.alpha_t

    def calibrate_offline(self, scores, events) -> dict:
        """Sweep a resolved history, return the realized coverage at the running threshold (a
        diagnostic; does not change the deployed band unless ``enabled``)."""
        s = np.asarray(scores, dtype=float)
        y = np.asarray(events, dtype=float)
        covered = 0
        for si, yi in zip(s.tolist(), y.tolist()):
            thr = float(np.quantile(s, max(0.0, min(1.0, 1.0 - self.alpha_t))))
            decision = si >= thr
            self.update(int(decision == bool(yi >= 0.5)))
            covered += int(decision == bool(yi >= 0.5))
        return {"alpha_t": self.alpha_t, "realized_coverage": covered / y.size if y.size else None,
                "n": int(y.size)}

    def to_params(self) -> dict:
        return {"alpha_target": self.alpha_target, "gamma": self.gamma, "alpha_t": self.alpha_t,
                "enabled": self.enabled}
