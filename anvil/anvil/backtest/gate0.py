"""Gate-0 — the kill switch. Per target, does the high-confidence bucket sustain USABLE accuracy at
USABLE coverage, with the decision threshold chosen INSIDE the walk-forward loop and counted as a trial?

This orchestrates primitives that already exist (it adds no new statistics):

  * calibration (``CalibrationService.calibrate``) so "accuracy" is CALIBRATED accuracy, not a raw score;
  * the in-loop, out-of-fold, **trial-counted** threshold sweep (``risk_coverage_threshold`` for the
    accuracy operating point, ``ev_coverage_threshold`` for the MONEY operating point);
  * the full anti-overfit battery (``validate_cells``: Deflated Sharpe, global PBO across the *grid of
    thresholds tried*, Harvey-t, walk-forward + combinatorial OOF edge), with ``n_trials`` from the
    persisted ``TrialRegistry`` and ``embargo`` = the label horizon.

Pass bar (per target): ≥ ``accuracy_target`` CALIBRATED accuracy at ≥ ``min_coverage`` coverage, with the
operating cell ``headline_eligible`` (DSR ≥ 0.95, PBO ≤ 0.5, Harvey t ≥ 3, both OOF edges > 0), trials
counted, AND positive realized EV where a P&L target is available. The whole point is honest discovery —
abstaining ("not enough evidence yet") is a correct outcome, NOT a failure to be tuned away.

EV-at-coverage is emitted alongside accuracy-at-coverage because accuracy isn't money: the operating
point is set on EV × coverage (the realized, net-of-cost per-decision edge), which is the link to P&L.
"""

from __future__ import annotations

import numpy as np

from ..calibration import CALIBRATION_VERSION
from ..calibration.conformal import ev_coverage_threshold, risk_coverage_threshold
from ..ledger.ledger import KIND_PROB_TOUCH, KIND_TRADE_WIN, KIND_VRP_RICH
from ..tips.store import GATE_VERSION
from .aggregate import new_cell, validate_cells
from .horizon import embargo_from_pairs
from .validation import purged_walk_forward_splits

EQUITY_STRUCTURE = "equity_directional"

# Default tau grid (0.50..0.95), matching the conformal module's frontier grid.
_GRID = tuple(round(0.50 + 0.01 * i, 4) for i in range(46))

# (target, ledger kind, structure-filter, has_per_trade_returns)
#   structure-filter: "option" => structure != equity_directional ; "equity" => == ; None => no filter
_TARGETS = (
    ("conviction", KIND_TRADE_WIN, "option", True),
    ("equity", KIND_TRADE_WIN, "equity", True),
    ("touch", KIND_PROB_TOUCH, None, False),
    ("vrp", KIND_VRP_RICH, None, False),
)

# Source-class menu per kind (backtest first, then live) — Gate-0 evaluates each independently (firewall).
_TRADE_SOURCES = ("tip_backtest", "tip_live")
_STRUCT_SOURCES = ("struct_backtest", "struct_live")


def _nanmean(xs) -> float | None:
    a = np.asarray([x for x in xs if x is not None], dtype=float)
    a = a[np.isfinite(a)]
    return float(a.mean()) if a.size else None


def _trade_win_samples(issued_store, source_class: str, structure_filter: str | None) -> list[dict]:
    """Per-decision resolved samples for a trade-win target from the issued-tip store, filtered to the
    option vs equity structure family."""
    rows = issued_store.resolved_samples(sources=(source_class,))
    out = []
    for r in rows:
        is_equity = r.get("structure") == EQUITY_STRUCTURE
        if structure_filter == "equity" and not is_equity:
            continue
        if structure_filter == "option" and is_equity:
            continue
        out.append(r)
    return out


def _structural_samples(ledger, kind: str, source_class: str) -> list[dict]:
    """Per-decision resolved samples for a structural target (touch/vrp) from the calibration ledger.
    These carry no per-trade P&L (no act-set return), so EV-at-coverage is omitted for them."""
    out = []
    for prob, event, created, params in ledger.resolved_ordered(kind=kind, classes=(source_class,)):
        p = params or {}
        h = p.get("horizon_days") or p.get("days")
        out.append({
            "raw_score": float(prob), "event": int(event), "ret": None,
            "day": (created or "")[:10], "regime_bucket": p.get("regime_bucket", ""),
            "created_ts": created or "", "resolve_ts": p.get("resolve_ts", "") or "",
            "structure": p.get("structure", ""), "horizon_days": float(h) if h else None,
        })
    return out


def _embargo_for(samples: list[dict], *, default: int = 5) -> int:
    """Label horizon → OOF embargo. Trade-win samples carry (created_ts, resolve_ts) trading-day spans;
    structural samples fall back to the median ``horizon_days`` in their params."""
    pairs = [(s.get("created_ts", ""), s.get("resolve_ts", "")) for s in samples
             if s.get("created_ts") and s.get("resolve_ts")]
    if pairs:
        return embargo_from_pairs(pairs)
    hs = [s["horizon_days"] for s in samples if s.get("horizon_days")]
    return max(1, int(round(float(np.median(hs))))) if hs else int(default)


def _coverage_curve(cal: np.ndarray, events: np.ndarray, rets: np.ndarray | None,
                    grid) -> dict:
    """Descriptive (in-sample) accuracy/EV-vs-coverage curve for the report plot. The VERDICT uses the
    out-of-fold picks, not this curve — this is for the reviewable shape only."""
    avg_win = avg_loss = None
    if rets is not None:
        w = rets[rets > 0]
        ll = rets[rets < 0]
        avg_win = float(w.mean()) if w.size else 0.0
        avg_loss = float(ll.mean()) if ll.size else 0.0  # negative
    taus, covs, accs, r_evs, m_evs = [], [], [], [], []
    for tau in grid:
        m = cal >= tau
        cov = float(m.mean())
        if cov <= 0:
            continue
        taus.append(float(tau))
        covs.append(cov)
        accs.append(float(events[m].mean()))
        if rets is not None:
            r_evs.append(float(rets[m].mean()))
            p = cal[m]
            m_evs.append(float((p * avg_win + (1.0 - p) * avg_loss).mean()))
    out = {"tau": taus, "coverage": covs, "accuracy": accs}
    if rets is not None:
        out["realized_ev"] = r_evs
        out["model_ev"] = m_evs
    return out


def _oof_metrics_at(cal: np.ndarray, events: np.ndarray, rets: np.ndarray | None, tau: float, *,
                    embargo: int, n_splits: int = 5) -> dict:
    """Honest OUT-OF-FOLD coverage / calibrated accuracy / realized EV at a FIXED operating ``tau``
    (test folds of an embargoed walk-forward split), so all three verdict numbers share one operating
    point."""
    splits = purged_walk_forward_splits(int(cal.size), n_splits=n_splits, embargo=max(0, int(embargo)))
    covs, accs, evs = [], [], []
    for _train, test in splits:
        t = np.asarray(test)
        m = cal[t] >= tau
        covs.append(float(m.mean()))
        accs.append(float(events[t][m].mean()) if bool(m.any()) else None)
        if rets is not None:
            evs.append(float(rets[t][m].mean()) if bool(m.any()) else None)
    return {"coverage": _nanmean(covs), "accuracy": _nanmean(accs),
            "ev": _nanmean(evs) if rets is not None else None, "n_folds": len(splits)}


def _threshold_battery(target: str, source_class: str, cal: np.ndarray, events: np.ndarray,
                       rets: np.ndarray | None, days: list[str], grid, *, embargo: int,
                       operating_tau: float, min_samples: int, n_trials: int | None) -> dict:
    """Run the full anti-overfit battery treating EACH tau on the grid as a config (cell), so the global
    PBO honestly tests whether the best-in-sample threshold stays best out-of-sample, and the operating
    cell's verdict carries DSR / Harvey-t / both OOF-edge checks. Returns the operating cell's report +
    the global PBO across thresholds."""
    cells: dict = {}
    for tau in grid:
        m = cal >= tau
        idx = np.nonzero(m)[0]
        # Independent act-days must clear min_samples (day-blocked n), else skip this config.
        if len({days[i] for i in idx}) < min_samples:
            continue
        cell = new_cell()
        for i in idx:
            r = float(rets[i]) if rets is not None else (float(events[i]) - 0.5)
            day = days[i]
            cell["returns"].append(r)
            cell["net"].append(r)
            cell["conv"].append(float(cal[i]))
            cell["wins"] += int(events[i] > 0.5)
            cell["by_day"][day].append(r)
        cells[(target, f"tau={float(tau):.2f}", source_class)] = cell
    if not cells:
        return {"degraded": True, "reason": "no threshold cell cleared min act-days", "n_cells": 0,
                "headline_eligible": False, "global_pbo": float("nan")}
    res_days = sorted({d for c in cells.values() for d in c["by_day"]})
    reports, gpbo = validate_cells(cells, res_days, min_samples=min_samples, n_trials=n_trials,
                                   embargo=embargo)
    op_key_bucket = f"tau={float(operating_tau):.2f}"
    op = next((r for r in reports if r.regime_bucket == op_key_bucket), None)
    if op is None:  # operating tau's act-set was too thin to form a cell — take the nearest evaluated tau
        op = min(reports, key=lambda r: abs(float(r.regime_bucket.split("=")[1]) - float(operating_tau)),
                 default=None)
    return {
        "degraded": False,
        "n_cells": len(cells),
        "global_pbo": gpbo,
        "operating_bucket": (op.regime_bucket if op else None),
        "headline_eligible": bool(op.headline_eligible) if op else False,
        "dsr": (op.dsr if op else float("nan")),
        "pbo": (op.pbo if op else float("nan")),
        "t_stat": (op.t_stat if op else float("nan")),
        "cost_adjusted_edge": (op.cost_adjusted_edge if op else float("nan")),
        "n": (op.n if op else 0),
        "win_rate": (op.win_rate if op else float("nan")),
        "mean_conviction": (op.mean_conviction if op else float("nan")),
    }


def _run_target(target: str, kind: str, structure_filter: str | None, has_returns: bool,
                samples: list[dict], *, source_class: str, calibrators, accuracy_target: float,
                min_coverage: float, accuracy_floor: float, min_samples: int, grid,
                trial_registry) -> dict:
    n = len(samples)
    base = {"target": target, "source_class": source_class, "kind": kind, "n": n}
    if n < max(min_samples * 2, 20):
        return {**base, "evaluable": False, "note": "insufficient evidence (too few resolved samples)",
                "verdict": {"pass": False, "reasons": ["insufficient evidence"]}}

    raw = np.array([float(s["raw_score"]) for s in samples], dtype=float)
    events = np.array([float(s["event"]) for s in samples], dtype=float)
    days = [s["day"] for s in samples]
    rets = None
    if has_returns:
        rv = np.array([s["ret"] if s["ret"] is not None else np.nan for s in samples], dtype=float)
        rets = rv if np.isfinite(rv).all() else None

    calibrated = bool(calibrators.is_calibrated(target, source_class)) if calibrators else False
    if calibrators:
        cal = np.array([float(calibrators.calibrate(target, float(x), source_class=source_class))
                        for x in raw], dtype=float)
    else:
        cal = raw.copy()
    embargo = _embargo_for(samples)

    # In-loop, OOF, TRIAL-COUNTED threshold picks. Each sweep bumps the registry so it raises the bar.
    acc_pick = risk_coverage_threshold(
        cal, events, accuracy_floor=accuracy_floor, embargo=embargo, trial_registry=trial_registry,
        trial_scope=f"gate0:{target}:{source_class}:acc")
    ev_pick = None
    if rets is not None:
        ev_pick = ev_coverage_threshold(
            cal, rets, embargo=embargo, trial_registry=trial_registry,
            trial_scope=f"gate0:{target}:{source_class}:ev")

    operating = "ev" if ev_pick is not None else "accuracy"
    operating_tau = float(ev_pick["tau"] if ev_pick is not None else acc_pick["tau"])
    at_op = _oof_metrics_at(cal, events, rets, operating_tau, embargo=embargo)

    scope_total = None
    if trial_registry is not None:
        try:
            scope_total = int(trial_registry.total(f"gate0:{target}:{source_class}:acc")) + \
                (int(trial_registry.total(f"gate0:{target}:{source_class}:ev")) if ev_pick else 0)
        except Exception:  # noqa: BLE001
            scope_total = None
    battery = _threshold_battery(target, source_class, cal, events, rets, days, grid, embargo=embargo,
                                 operating_tau=operating_tau, min_samples=min_samples,
                                 n_trials=scope_total)

    cov = at_op["coverage"]
    acc = at_op["accuracy"]
    ev = at_op["ev"]
    reasons: list[str] = []
    if not battery.get("headline_eligible"):
        reasons.append("battery not headline-eligible (DSR/PBO/t/OOF-edge)")
    if cov is None or cov < min_coverage:
        reasons.append(f"coverage {cov} < {min_coverage}")
    if acc is None or acc < accuracy_target:
        reasons.append(f"calibrated accuracy {acc} < {accuracy_target}")
    if rets is not None and (ev is None or ev <= 0):
        reasons.append(f"EV-at-coverage {ev} not positive")
    if not calibrated:
        reasons.append("uncalibrated (identity map — accuracy is raw, not earned out-of-fold)")
    passed = len(reasons) == 0

    return {
        **base,
        "evaluable": True,
        "calibrated": calibrated,
        "embargo": int(embargo),
        "operating_point": operating,
        "operating_tau": operating_tau,
        "coverage": cov,
        "accuracy": acc,
        "realized_ev": ev,
        "acc_pick": acc_pick,
        "ev_pick": ev_pick,
        "battery": battery,
        "trials": scope_total,
        "curve": _coverage_curve(cal, events, rets, grid),
        "verdict": {"pass": passed, "reasons": reasons},
        "note": "" if calibrated else "identity (uncalibrated until depth)",
    }


def run_gate0(*, issued_store, ledger, calibrators=None, sources: dict | None = None,
              accuracy_target: float = 0.65, min_coverage: float = 0.10, accuracy_floor: float = 0.52,
              min_samples: int = 8, grid=_GRID, trial_registry=None, now_ts: str = "",
              date_range: tuple[str, str] | None = None, depth_days: int | None = None,
              provisional: bool = True) -> dict:
    """Run Gate-0 across every (target, source_class). ``sources`` overrides the default class menu per
    kind (e.g. ``{"trade": ("tip_backtest",), "struct": ("struct_backtest",)}``). Returns the full,
    report-ready result; the caller writes the artifact with ``gate_report.write_gate0_report``."""
    src = sources or {}
    trade_sources = tuple(src.get("trade", _TRADE_SOURCES))
    struct_sources = tuple(src.get("struct", _STRUCT_SOURCES))

    target_results: list[dict] = []
    for target, kind, sfilter, has_ret in _TARGETS:
        classes = trade_sources if kind == KIND_TRADE_WIN else struct_sources
        for sc in classes:
            if kind == KIND_TRADE_WIN:
                samples = _trade_win_samples(issued_store, sc, sfilter)
            else:
                samples = _structural_samples(ledger, kind, sc)
            if not samples:
                continue  # nothing resolved for this (target, source) — silently skip (no evidence)
            target_results.append(_run_target(
                target, kind, sfilter, has_ret, samples, source_class=sc, calibrators=calibrators,
                accuracy_target=accuracy_target, min_coverage=min_coverage, accuracy_floor=accuracy_floor,
                min_samples=min_samples, grid=grid, trial_registry=trial_registry))

    passing = [f"{t['target']}/{t['source_class']}" for t in target_results
               if t.get("verdict", {}).get("pass")]
    go = len(passing) > 0
    summary = (
        f"GO — {', '.join(passing)} sustains usable accuracy at usable coverage."
        if go else
        "NO-GO / ABSTAIN — no target sustains the bar yet. 'Not enough evidence' is a correct, honest "
        "outcome on this depth; re-certify when the backfill lands."
    )
    return {
        "generated_ts": now_ts,
        "gate_version": GATE_VERSION,
        "calibration_version": CALIBRATION_VERSION,
        "thresholds": {"accuracy_target": accuracy_target, "min_coverage": min_coverage,
                       "accuracy_floor": accuracy_floor, "battery_min_samples": min_samples},
        "data": {"trade_sources": list(trade_sources), "struct_sources": list(struct_sources),
                 "date_range": list(date_range) if date_range else None, "depth_days": depth_days,
                 "provisional": provisional},
        "targets": target_results,
        "verdict": {"pass": go, "passing_targets": passing, "summary": summary},
    }
