"""Out-of-fold calibration quality (OVERRIDE 2): the ECE the DoD trusts is measured on held-out
purged walk-forward folds, never in-sample."""

from __future__ import annotations

import numpy as np

from anvil.calibration.crossval import oof_calibration_metrics, oof_predictions
from anvil.ledger.scoring import expected_calibration_error


def _miscalibrated(n=800, bias=0.18, seed=1):
    rng = np.random.default_rng(seed)
    raw = rng.uniform(0.2, 0.95, n)
    true_p = np.clip(raw - bias, 0.01, 0.99)
    y = (rng.random(n) < true_p).astype(int)
    return raw, y


def test_oof_ece_below_threshold_and_below_before():
    raw, y = _miscalibrated()
    m = oof_calibration_metrics(raw, y, embargo=5, n_splits=5, min_samples=50, blend_floor_n=200)
    assert m["n_folds"] >= 3
    assert m["ece_after"] < m["ece_before"]  # genuine generalization gain
    assert m["ece_after"] < 0.10  # the DoD bar


def test_oof_before_after_on_same_rows():
    # ece_before is the RAW-score ECE on the SAME out-of-fold rows as ece_after (apples-to-apples).
    raw, y = _miscalibrated()
    cal_p, raw_p, lab, idx, _nf = oof_predictions(raw, y, embargo=5, n_splits=5)
    m = oof_calibration_metrics(raw, y, embargo=5, n_splits=5)
    assert abs(m["ece_before"] - expected_calibration_error(raw_p, lab)) < 1e-9
    assert abs(m["ece_after"] - expected_calibration_error(cal_p, lab)) < 1e-9
    assert cal_p.size == raw_p.size == lab.size == idx.size


def test_oof_no_gain_when_already_calibrated():
    # Perfectly calibrated data: out-of-fold isotonic cannot conjure a (meaningful) gain.
    rng = np.random.default_rng(7)
    raw = rng.uniform(0.05, 0.95, 800)
    y = (rng.random(800) < raw).astype(int)
    m = oof_calibration_metrics(raw, y, embargo=5, n_splits=5)
    assert m["ece_before"] < 0.08  # already near-diagonal
    assert m["ece_after"] <= m["ece_before"] + 0.05  # no large spurious improvement


def test_oof_empty_when_too_few_samples():
    m = oof_calibration_metrics([0.6, 0.7], [0, 1], embargo=1, n_splits=5)
    assert m["n_oof"] == 0
    assert m["ece_after"] != m["ece_after"]  # NaN
