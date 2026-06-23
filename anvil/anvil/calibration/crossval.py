"""Out-of-fold calibration quality — the only ECE the store and the DoD are allowed to trust.

In-sample ECE improvement after an isotonic fit is GUARANTEED and meaningless (the fit minimizes it
by construction). So every quality number reported for a calibrator is measured OUT-OF-FOLD: fit on
each purged walk-forward TRAIN block, predict the held-out TEST block, pool the test predictions, and
score those. We reuse the Phase 0-C purged splits (``backtest.validation.purged_walk_forward_splits``)
so the same leak-safety that guards the significance gate guards the calibration estimate — train
labels that resolve into a test block are embargoed out.

``ece_before`` and ``ece_after`` are BOTH computed on the same pooled out-of-fold test rows (raw score
vs calibrated), so the comparison is apples-to-apples.
"""

from __future__ import annotations

import numpy as np

from ..backtest.validation import purged_walk_forward_splits
from ..ledger.scoring import brier_score, expected_calibration_error
from .isotonic import fit_calibrator


def oof_predictions(scores, events, *, embargo: int = 1, n_splits: int = 5,
                    min_samples: int = 50, blend_floor_n: int = 200):
    """Pooled out-of-fold ``(calibrated, raw, label, test_idx)`` over purged walk-forward splits.

    ``scores``/``events`` MUST be time-ordered (oldest first) — the walk-forward trains on the past
    and tests forward. Each test block is calibrated by a map fit ONLY on the embargoed past.
    ``test_idx`` are the original indices of the pooled rows (so callers can align regimes etc.).
    Arrays are empty when there are too few samples to split.
    """
    s = np.asarray(scores, dtype=float)
    y = np.asarray(events, dtype=float)
    n = s.size
    splits = purged_walk_forward_splits(n, n_splits=int(n_splits), embargo=max(0, int(embargo)))
    cal_p: list[float] = []
    raw_p: list[float] = []
    lab: list[float] = []
    idx: list[int] = []
    for train, test in splits:
        cal, _ = fit_calibrator(s[train], y[train], min_samples=min_samples,
                                blend_floor_n=blend_floor_n)
        pred = np.atleast_1d(np.asarray(cal.predict(s[test]), dtype=float))
        cal_p.extend(pred.tolist())
        raw_p.extend(s[test].tolist())
        lab.extend(y[test].tolist())
        idx.extend(list(test))
    return (np.asarray(cal_p), np.asarray(raw_p), np.asarray(lab),
            np.asarray(idx, dtype=int), len(splits))


def oof_calibration_metrics(scores, events, *, embargo: int = 1, n_splits: int = 5,
                            min_samples: int = 50, blend_floor_n: int = 200,
                            n_bins: int = 10) -> dict:
    """Out-of-fold ECE/Brier before (raw) and after (calibrated), measured on the SAME held-out rows.

    ``ece_after < ece_before`` here is a genuine generalization gain, not a fit artifact. NaNs when
    there isn't enough data to split (the honest "can't measure yet" state)."""
    s = np.asarray(scores, dtype=float)
    y = np.asarray(events, dtype=float)
    n = int(s.size)
    cal_p, raw_p, lab, _idx, n_folds = oof_predictions(
        s, y, embargo=embargo, n_splits=n_splits, min_samples=min_samples,
        blend_floor_n=blend_floor_n)
    if cal_p.size == 0:
        return {"n": n, "n_folds": n_folds, "n_oof": 0,
                "ece_before": float("nan"), "ece_after": float("nan"),
                "brier_before": float("nan"), "brier_after": float("nan")}
    return {
        "n": n,
        "n_folds": n_folds,
        "n_oof": int(cal_p.size),
        "ece_before": expected_calibration_error(raw_p, lab, n_bins),
        "ece_after": expected_calibration_error(cal_p, lab, n_bins),
        "brier_before": brier_score(raw_p, lab),
        "brier_after": brier_score(cal_p, lab),
    }
