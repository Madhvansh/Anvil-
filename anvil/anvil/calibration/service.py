"""The service seam — load calibrators for predict-time use, and fit them on cadence.

``CalibrationService`` is a cheap, read-only object (hydrated from ``CalibratorStore``) held by the
predict/strategy/decision-brief layers. Applying a map is a pure lookup with a SAFE identity fallback,
so behavior is byte-identical until a map is fit. ``fit_all_targets`` is the nightly/CLI fit: it reads
resolved history PER SOURCE-CLASS (never mixed), fits each target's deployed map on all available
past data, measures quality OUT-OF-FOLD, derives the abstain threshold on train→test folds, and
persists — stamping ``CALIBRATION_VERSION`` for freshness.
"""

from __future__ import annotations

import numpy as np

from ..ledger.ledger import (
    KIND_PROB_TOUCH,
    KIND_TRADE_WIN,
    KIND_VRP_RICH,
)
from . import CALIBRATION_VERSION
from .conformal import mondrian_thresholds
from .crossval import oof_calibration_metrics, oof_predictions
from .isotonic import IdentityCalibrator, calibrator_from_params, fit_calibrator
from .store import CalibratorRecord, CalibratorStore

EQUITY_STRUCTURE = "equity_directional"

# (target, ledger kind, source-classes to fit independently, structure-filter)
#   structure-filter: "option" => structure != equity_directional ; "equity" => == ; None => no filter
_TARGETS = (
    ("conviction", KIND_TRADE_WIN, ("tip_backtest", "tip_live"), "option"),
    ("equity", KIND_TRADE_WIN, ("tip_backtest", "tip_live"), "equity"),
    ("touch", KIND_PROB_TOUCH, ("struct_backtest", "struct_live"), None),
    ("vrp", KIND_VRP_RICH, ("struct_backtest", "struct_live"), None),
)


class CalibrationService:
    """Read-only predict-time calibration lookups; identity-safe when a map is absent."""

    def __init__(self, records: list[CalibratorRecord] | None = None):
        self._cal: dict[tuple[str, str], object] = {}
        self._thr: dict[tuple[str, str], dict] = {}
        self._meta: dict[tuple[str, str], CalibratorRecord] = {}
        for r in records or []:
            key = (r.target, r.source_class)
            self._cal[key] = calibrator_from_params(r.params)
            self._thr[key] = {"tau": r.abstain_tau, "mondrian": (r.conformal or {}).get("mondrian", {})}
            self._meta[key] = r

    def is_calibrated(self, target: str, source_class: str) -> bool:
        c = self._cal.get((target, source_class))
        return c is not None and not isinstance(c, IdentityCalibrator)

    def calibrate(self, target: str, raw, *, source_class: str):
        """Map a raw score to a calibrated probability; returns ``raw`` unchanged when no map exists."""
        if raw is None:
            return raw
        c = self._cal.get((target, source_class))
        if c is None:
            return raw
        return float(np.atleast_1d(c.predict(raw))[0])

    def abstain_threshold(self, target: str, *, source_class: str, regime_bucket: str | None = None,
                          fallback: float) -> float:
        th = self._thr.get((target, source_class))
        if not th:
            return fallback
        mond = th.get("mondrian") or {}
        if regime_bucket and regime_bucket in mond and mond[regime_bucket].get("tau") is not None:
            return float(mond[regime_bucket]["tau"])
        tau = th.get("tau")
        return float(tau) if tau is not None else fallback


def _embargo_from(rows, default: int = 5) -> int:
    """Label horizon (in samples, approximated by trading days) for the purge gap."""
    hs = []
    for _p, _e, _ts, params in rows:
        h = (params or {}).get("horizon_days") or (params or {}).get("days")
        if h:
            hs.append(float(h))
    return max(1, int(round(float(np.median(hs))))) if hs else int(default)


def _filter_rows(rows, structure_filter: str | None):
    if structure_filter is None:
        return rows
    want_equity = structure_filter == "equity"
    out = []
    for r in rows:
        struct = (r[3] or {}).get("structure")
        is_equity = struct == EQUITY_STRUCTURE
        if is_equity == want_equity:
            out.append(r)
    return out


def fit_all_targets(*, ledger, store: CalibratorStore, min_samples: int = 50,
                    blend_floor_n: int = 200, accuracy_floor: float = 0.52, n_splits: int = 5,
                    now_ts: str = "", trial_registry=None,
                    only_source_class: str | None = None) -> dict:
    """Fit + persist every ``(target, source_class)`` calibrator from resolved ledger history.
    Returns a per-key summary. Each fit reads ONLY its own source class (the firewall)."""
    summary: dict = {}
    for target, kind, classes, sfilter in _TARGETS:
        for sc in classes:
            if only_source_class and sc != only_source_class:
                continue
            rows = _filter_rows(ledger.resolved_ordered(kind=kind, classes=(sc,)), sfilter)
            scores = [r[0] for r in rows]
            events = [r[1] for r in rows]
            regimes = [(r[3] or {}).get("regime_bucket", "") for r in rows]
            embargo = _embargo_from(rows)
            rec = _fit_one(target, sc, scores, events, regimes, embargo=embargo,
                           min_samples=min_samples, blend_floor_n=blend_floor_n,
                           accuracy_floor=accuracy_floor, n_splits=n_splits, now_ts=now_ts,
                           trial_registry=trial_registry)
            store.upsert(rec)
            summary[f"{target}/{sc}"] = {"kind": rec.kind, "n": rec.n, "n_folds": rec.n_folds,
                                         "ece_before": rec.ece_before, "ece_after": rec.ece_after,
                                         "abstain_tau": rec.abstain_tau,
                                         "lambda": rec.lambda_blend}
    return summary


def _fit_one(target, source_class, scores, events, regimes, *, embargo, min_samples, blend_floor_n,
             accuracy_floor, n_splits, now_ts, trial_registry) -> CalibratorRecord:
    n = len(scores)
    cal, diag = fit_calibrator(scores, events, min_samples=min_samples, blend_floor_n=blend_floor_n)
    metrics = oof_calibration_metrics(scores, events, embargo=embargo, n_splits=n_splits,
                                      min_samples=min_samples, blend_floor_n=blend_floor_n)
    # HONESTY GUARD: only DEPLOY a fitted map if it demonstrably beats the raw score OUT-OF-FOLD.
    # A map that doesn't generalize (ece_after ≥ ece_before, or unmeasurable) is dropped to identity —
    # we never apply a transform that isn't earned out-of-fold. The OOF metrics are still recorded so
    # the report shows WHY a target stayed identity (e.g. conviction is already ~calibrated).
    eb, ea = metrics["ece_before"], metrics["ece_after"]
    improves = (ea == ea) and (eb == eb) and (ea < eb)  # both finite and a strict OOF gain
    if not isinstance(cal, IdentityCalibrator) and not improves:
        cal, diag = IdentityCalibrator(), {**diag, "kind": "identity", "lambda": diag["lambda"],
                                           "degraded": True}
    # The abstain threshold operates on the CALIBRATED probability at predict time, so derive it from
    # the OUT-OF-FOLD calibrated predictions (never the raw scores, never in-sample). Regimes are
    # aligned to the pooled OOF rows via their original indices (Mondrian conditioning).
    cal_p, _raw, lab, test_idx, _nf = oof_predictions(
        scores, events, embargo=embargo, n_splits=n_splits, min_samples=min_samples,
        blend_floor_n=blend_floor_n)
    if cal_p.size >= int(min_samples) and len(set(int(v) for v in lab.tolist())) >= 2:
        oof_regimes = [regimes[i] for i in test_idx.tolist()]
        mond = mondrian_thresholds(cal_p, lab, oof_regimes, accuracy_floor=accuracy_floor,
                                   embargo=1, n_splits=n_splits, trial_registry=trial_registry,
                                   trial_scope=f"calib:{target}:{source_class}")
        rc = mond["__global__"]
    else:
        mond = {}
        rc = {"tau": None, "degraded": True}
    return CalibratorRecord(
        target=target, source_class=source_class, kind=diag["kind"], params=cal.to_params(),
        n=n, n_folds=int(metrics["n_folds"]), ece_before=metrics["ece_before"],
        ece_after=metrics["ece_after"], brier_before=metrics["brier_before"],
        brier_after=metrics["brier_after"], lambda_blend=float(diag["lambda"]),
        abstain_tau=rc.get("tau"), conformal={"mondrian": mond, "global": rc},
        fit_ts=now_ts, model_version=CALIBRATION_VERSION,
    )
