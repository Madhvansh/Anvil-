"""Persisted calibrators: param roundtrip, the (target, source_class) firewall, version stamp."""

from __future__ import annotations

import numpy as np

from anvil.calibration import CALIBRATION_VERSION
from anvil.calibration.isotonic import IsotonicCalibrator
from anvil.calibration.store import CalibratorRecord, CalibratorStore


def _iso_record(target, sc, knots_y, **kw):
    cal = IsotonicCalibrator(np.array([0.0, 0.5, 1.0]), np.array(knots_y))
    return CalibratorRecord(target=target, source_class=sc, kind="isotonic",
                            params=cal.to_params(), model_version=CALIBRATION_VERSION, **kw)


def test_roundtrip_params_rehydrate_equal_predictions(tmp_path):
    store = CalibratorStore(str(tmp_path / "c.duckdb"))
    try:
        rec = _iso_record("conviction", "tip_backtest", [0.0, 0.3, 0.6], n=400, abstain_tau=0.66,
                          ece_before=0.15, ece_after=0.08)
        store.upsert(rec)
        got = store.get("conviction", "tip_backtest")
        assert got is not None
        svc = store.load_service()
        # rehydrated calibrator predicts identically to the original
        expected = float(IsotonicCalibrator(np.array([0.0, 0.5, 1.0]), np.array([0.0, 0.3, 0.6])).predict(0.8))
        assert abs(svc.calibrate("conviction", 0.8, source_class="tip_backtest") - expected) < 1e-9
    finally:
        store.close()


def test_source_class_firewall_independent_rows(tmp_path):
    store = CalibratorStore(str(tmp_path / "c.duckdb"))
    try:
        store.upsert(_iso_record("conviction", "tip_backtest", [0.0, 0.3, 0.6], n=400))
        store.upsert(_iso_record("conviction", "tip_live", [0.0, 0.45, 0.9], n=120))
        # the two classes are different rows; fitting/replacing one never mutates the other
        svc = store.load_service()
        bt = svc.calibrate("conviction", 0.8, source_class="tip_backtest")
        lv = svc.calibrate("conviction", 0.8, source_class="tip_live")
        assert abs(bt - lv) > 1e-3  # genuinely different maps
        assert len(store.all()) == 2
    finally:
        store.close()


def test_version_stamp_and_oof_metrics_persist(tmp_path):
    store = CalibratorStore(str(tmp_path / "c.duckdb"))
    try:
        store.upsert(_iso_record("vrp", "struct_backtest", [0.0, 0.4, 0.8], n=300,
                                 ece_before=0.2, ece_after=0.07))
        row = next(r for r in store.all() if r["target"] == "vrp")
        assert row["model_version"] == CALIBRATION_VERSION
        assert row["ece_before"] == 0.2 and row["ece_after"] == 0.07
        assert row["ece_after"] < row["ece_before"]
    finally:
        store.close()


def test_upsert_replaces_same_key(tmp_path):
    store = CalibratorStore(str(tmp_path / "c.duckdb"))
    try:
        store.upsert(_iso_record("equity", "tip_live", [0.0, 0.3, 0.6], n=50))
        store.upsert(_iso_record("equity", "tip_live", [0.0, 0.4, 0.8], n=200))
        rows = [r for r in store.all() if r["target"] == "equity"]
        assert len(rows) == 1 and rows[0]["n"] == 200  # replaced, not duplicated
    finally:
        store.close()
