"""CalibrationService + fit_all_targets: identity-safe when empty, per-class fit with no mixing,
maps strengthen as resolved history accrues."""

from __future__ import annotations

import numpy as np

from anvil.calibration.service import CalibrationService, fit_all_targets
from anvil.calibration.store import CalibratorStore
from anvil.ledger.ledger import CalibrationLedger, Forecast, KIND_TRADE_WIN


def _seed_conviction(led, source, n, bias, seed, structure="short_strangle"):
    """Seed ``n`` resolved conviction forecasts under ``source`` overconfident by ``bias``."""
    rng = np.random.default_rng(seed)
    for i in range(n):
        conv = float(rng.uniform(0.55, 0.9))
        win = 1 if rng.random() < max(0.01, conv - bias) else 0
        f = Forecast(
            underlying="NIFTY", created_ts=f"2025-09-{(i % 27) + 1:02d}T15:{(i // 27) % 60:02d}:{i % 60:02d}+05:30",
            resolve_ts="2025-12-30T16:00:00+05:30", kind=KIND_TRADE_WIN,
            params={"structure": structure, "regime_bucket": "pin_low_vol", "horizon_days": 5, "i": i},
            prob=conv, spot=100.0, forward=100.0, source=source)
        fid = led.record(f)
        led.resolve(fid, 1.0 if win else -1.0, resolved_ts="2025-12-30T16:00:00+05:30")


def test_identity_service_is_a_noop():
    svc = CalibrationService([])
    assert svc.is_calibrated("conviction", "tip_live") is False
    assert svc.calibrate("conviction", 0.83, source_class="tip_live") == 0.83
    assert svc.calibrate("vrp", None, source_class="struct_live") is None
    assert svc.abstain_threshold("vrp", source_class="struct_live", fallback=0.62) == 0.62


def test_fit_all_targets_per_class_no_mixing(tmp_path):
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    store = CalibratorStore(str(tmp_path / "store.duckdb"))
    try:
        _seed_conviction(led, "tip_backtest", 400, bias=0.22, seed=1)  # strongly overconfident
        _seed_conviction(led, "tip_live", 400, bias=0.10, seed=2)  # mildly overconfident
        fit_all_targets(ledger=led, store=store, min_samples=50, blend_floor_n=200,
                        accuracy_floor=0.52, n_splits=5, now_ts="2025-12-01T00:00:00Z")
        svc = store.load_service()
        # both classes are clearly miscalibrated → each deploys its own out-of-fold-validated map
        assert svc.is_calibrated("conviction", "tip_backtest")
        assert svc.is_calibrated("conviction", "tip_live")
        # the strongly-overconfident backtest map pulls 0.85 down MORE than the milder live map
        bt = svc.calibrate("conviction", 0.85, source_class="tip_backtest")
        lv = svc.calibrate("conviction", 0.85, source_class="tip_live")
        assert bt < lv  # the two classes learned different, non-mixed maps
        # touch/vrp have no data → identity
        assert svc.is_calibrated("touch", "struct_live") is False
    finally:
        led.close()
        store.close()


def test_struct_targets_identity_when_no_data(tmp_path):
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    store = CalibratorStore(str(tmp_path / "store.duckdb"))
    try:
        summary = fit_all_targets(ledger=led, store=store, min_samples=50, now_ts="t")
        for key in ("touch/struct_live", "vrp/struct_live", "conviction/tip_live"):
            assert summary[key]["kind"] == "identity"
            assert summary[key]["n"] == 0
    finally:
        led.close()
        store.close()


def test_refit_strengthens_with_n(tmp_path):
    # As resolved history accrues, the deployed map goes from identity (too thin to trust) to a real
    # out-of-fold-validated calibrator. (The λ glide itself is unit-tested in test_calibration_isotonic.)
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    store = CalibratorStore(str(tmp_path / "store.duckdb"))
    try:
        _seed_conviction(led, "tip_live", 30, bias=0.18, seed=3)  # below min_samples → identity
        fit_all_targets(ledger=led, store=store, min_samples=50, blend_floor_n=200, now_ts="t1")
        assert not store.load_service().is_calibrated("conviction", "tip_live")
        _seed_conviction(led, "tip_live", 400, bias=0.18, seed=4)  # accrue a clearly-miscalibrated set
        fit_all_targets(ledger=led, store=store, min_samples=50, blend_floor_n=200, now_ts="t2")
        assert store.load_service().is_calibrated("conviction", "tip_live")  # now a real map is deployed
    finally:
        led.close()
        store.close()


def test_no_deploy_when_no_oof_gain(tmp_path):
    # An already-well-calibrated stream (bias 0) yields no out-of-fold gain, so the fitted map is
    # dropped to identity — we never apply a transform that isn't earned OOF — even at large n. The
    # OOF metrics are still recorded so a report can show WHY it stayed identity.
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    store = CalibratorStore(str(tmp_path / "store.duckdb"))
    try:
        _seed_conviction(led, "tip_backtest", 400, bias=0.0, seed=9)  # honest by construction
        fit_all_targets(ledger=led, store=store, min_samples=50, blend_floor_n=200, now_ts="t")
        svc = store.load_service()
        assert not svc.is_calibrated("conviction", "tip_backtest")  # identity: no OOF improvement
        row = next(r for r in store.all() if r["target"] == "conviction")
        assert row["n"] == 400 and row["ece_before"] == row["ece_before"]  # metrics still recorded
    finally:
        led.close()
        store.close()


def test_only_source_class_filter(tmp_path):
    led = CalibrationLedger(str(tmp_path / "led.duckdb"))
    store = CalibratorStore(str(tmp_path / "store.duckdb"))
    try:
        _seed_conviction(led, "tip_backtest", 300, bias=0.18, seed=5)
        summary = fit_all_targets(ledger=led, store=store, min_samples=50, now_ts="t",
                                  only_source_class="tip_backtest")
        assert "conviction/tip_backtest" in summary
        assert "conviction/tip_live" not in summary  # filtered out
    finally:
        led.close()
        store.close()
