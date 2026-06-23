"""Isotonic/Platt/identity calibrators + the thin-data degradation gate."""

from __future__ import annotations

import numpy as np

from anvil.calibration.isotonic import (
    BlendedCalibrator,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    calibrator_from_params,
    fit_calibrator,
    pav_isotonic,
)
from anvil.ledger.scoring import brier_score, expected_calibration_error


def _miscalibrated(n=500, bias=0.18, seed=0):
    """Overconfident-by-``bias`` synthetic: scores spread across [0.2,0.95], true prob = score-bias."""
    rng = np.random.default_rng(seed)
    raw = rng.uniform(0.2, 0.95, n)
    true_p = np.clip(raw - bias, 0.01, 0.99)
    y = (rng.random(n) < true_p).astype(int)
    return raw, y


def test_pav_is_monotone_nondecreasing():
    rng = np.random.default_rng(1)
    x = rng.uniform(0, 1, 200)
    y = (rng.random(200) < x).astype(float)
    kx, ky = pav_isotonic(x, y)
    assert np.all(np.diff(kx) > 0)  # knots at sorted unique x
    assert np.all(np.diff(ky) >= -1e-12)  # non-decreasing fit


def test_pav_handles_ties_in_x():
    kx, ky = pav_isotonic([0.5, 0.5, 0.5, 0.9], [0, 1, 1, 1])
    assert kx.size == 2  # ties in x merged
    assert np.all(np.diff(ky) >= -1e-12)


def test_isotonic_reduces_in_sample_ece():
    raw, y = _miscalibrated()
    cal, diag = fit_calibrator(raw, y, min_samples=50, blend_floor_n=200)
    assert diag["kind"] == "isotonic"
    before = expected_calibration_error(raw, y)
    after = expected_calibration_error(np.atleast_1d(cal.predict(raw)), y)
    assert after < before


def test_thin_n_degrades_to_identity():
    raw, y = _miscalibrated(n=30)
    cal, diag = fit_calibrator(raw, y, min_samples=50, blend_floor_n=200)
    assert isinstance(cal, IdentityCalibrator)
    assert diag["degraded"] is True
    assert float(cal.predict(0.8)) == 0.8  # exact no-op


def test_single_outcome_class_degrades_to_identity():
    cal, diag = fit_calibrator(np.linspace(0.3, 0.9, 80), np.ones(80), min_samples=50)
    assert isinstance(cal, IdentityCalibrator)
    assert diag["degraded"] is True


def test_mid_n_blends_toward_identity():
    raw, y = _miscalibrated(n=120)
    cal, diag = fit_calibrator(raw, y, min_samples=50, blend_floor_n=200)
    assert isinstance(cal, BlendedCalibrator)
    assert 0.0 < diag["lambda"] < 1.0  # strictly between → glide path
    # blended prediction sits between identity and the full base map
    base, _ = fit_calibrator(raw, y, min_samples=50, blend_floor_n=1)  # forces full base
    p = 0.85
    full = float(base.predict(p))
    blended = float(cal.predict(p))
    assert min(p, full) - 1e-9 <= blended <= max(p, full) + 1e-9


def test_lambda_increases_with_n():
    lams = []
    for n in (70, 120, 180):
        _c, d = fit_calibrator(*_miscalibrated(n=n), min_samples=50, blend_floor_n=200)
        lams.append(d["lambda"])
    assert lams[0] < lams[1] < lams[2]


def test_platt_fallback_on_clustered_scores():
    # Only two distinct raw scores → PAV can't shape it; Platt path is taken.
    rng = np.random.default_rng(3)
    raw = np.where(rng.random(300) < 0.5, 0.55, 0.62)
    y = (rng.random(300) < (raw - 0.1)).astype(int)
    cal, diag = fit_calibrator(raw, y, min_samples=50, blend_floor_n=1)
    assert diag["kind"] == "platt"
    assert isinstance(cal, PlattCalibrator)


def test_brier_does_not_worsen_in_sample():
    raw, y = _miscalibrated()
    cal, _ = fit_calibrator(raw, y, min_samples=50, blend_floor_n=200)
    assert brier_score(np.atleast_1d(cal.predict(raw)), y) <= brier_score(raw, y) + 1e-6


def test_predict_scalar_and_array_shapes():
    cal = IsotonicCalibrator(np.array([0.0, 1.0]), np.array([0.1, 0.9]))
    assert isinstance(cal.predict(0.5), float)
    assert np.asarray(cal.predict([0.2, 0.8])).shape == (2,)


def test_params_roundtrip_all_kinds():
    raw, y = _miscalibrated()
    for cal in (IsotonicCalibrator(np.array([0.0, 1.0]), np.array([0.1, 0.9])),
                PlattCalibrator(a=2.0, b=-0.5),
                IdentityCalibrator(),
                fit_calibrator(raw, y, min_samples=50, blend_floor_n=120)[0]):
        re = calibrator_from_params(cal.to_params())
        assert abs(float(re.predict(0.7)) - float(cal.predict(0.7))) < 1e-9
