"""Risk-coverage abstain threshold (train→test) + Mondrian + the ACI interface (default off)."""

from __future__ import annotations

import numpy as np

from anvil.backtest.trials import TrialRegistry
from anvil.calibration.conformal import (
    AdaptiveConformal,
    mondrian_thresholds,
    risk_coverage_threshold,
)


def _calibrated_stream(n=900, seed=2):
    """A well-calibrated stream: realized win-rate ≈ score (so accuracy at tau ≈ tau)."""
    rng = np.random.default_rng(seed)
    p = rng.uniform(0.4, 0.95, n)
    y = (rng.random(n) < p).astype(int)
    return p, y


def test_threshold_respects_accuracy_floor_and_reports_on_test():
    p, y = _calibrated_stream()
    rc = risk_coverage_threshold(p, y, accuracy_floor=0.55, embargo=1, n_splits=5)
    assert not rc["degraded"]
    assert rc["coverage"] is not None and rc["accuracy"] is not None
    # the realized (test-fold) accuracy at tau* clears the floor (within fold noise)
    assert rc["accuracy"] >= 0.55 - 0.06


def test_higher_floor_pushes_tau_up():
    p, y = _calibrated_stream()
    lo = risk_coverage_threshold(p, y, accuracy_floor=0.55, embargo=1, n_splits=5)
    hi = risk_coverage_threshold(p, y, accuracy_floor=0.80, embargo=1, n_splits=5)
    assert hi["tau"] >= lo["tau"] - 1e-9  # raising the floor abstains more


def test_thin_data_conservative_abstain():
    rc = risk_coverage_threshold([0.6, 0.7], [0, 1], accuracy_floor=0.52, n_splits=5)
    assert rc["degraded"] is True
    assert rc["tau"] >= 0.85  # abstain-heavy fallback


def test_tau_grid_logged_to_trial_registry(tmp_path):
    reg = TrialRegistry(str(tmp_path / "trials.duckdb"))
    try:
        p, y = _calibrated_stream()
        rc = risk_coverage_threshold(p, y, accuracy_floor=0.55, embargo=1, n_splits=5,
                                     trial_registry=reg, trial_scope="calib:conviction:tip_backtest")
        assert reg.total("calib:conviction:tip_backtest") == rc["grid_size"]
    finally:
        reg.close()


def test_mondrian_per_regime_plus_global():
    p, y = _calibrated_stream()
    rng = np.random.default_rng(5)
    regimes = np.where(rng.random(p.size) < 0.5, "pin_low_vol", "trend_high_vol")
    out = mondrian_thresholds(p, y, regimes, accuracy_floor=0.55, embargo=1, n_splits=5, min_group=40)
    assert "__global__" in out
    assert "pin_low_vol" in out and "trend_high_vol" in out


def test_mondrian_thin_bucket_falls_back_to_global():
    p, y = _calibrated_stream(n=400)
    regimes = np.array(["pin_low_vol"] * 390 + ["rare"] * 10)
    out = mondrian_thresholds(p, y, regimes, accuracy_floor=0.55, embargo=1, n_splits=5, min_group=40)
    assert out["rare"] == out["__global__"]  # thin bucket reuses the global threshold


def test_aci_default_off_and_update_rule():
    aci = AdaptiveConformal(alpha_target=0.10, gamma=0.05, alpha_t=0.10)
    assert aci.enabled is False
    # ACI: a miss (err=1) LOWERS α_t (→ widen coverage next time); a hit (err=0) raises it.
    a0 = aci.alpha_t
    aci.update(covered=0)
    assert aci.alpha_t < a0
    a1 = aci.alpha_t
    aci.update(covered=1)
    assert aci.alpha_t > a1


def test_aci_alpha_stays_bounded():
    aci = AdaptiveConformal(alpha_target=0.1, gamma=0.5)
    for _ in range(50):
        aci.update(covered=0)
    assert 0.0 <= aci.alpha_t <= 1.0
