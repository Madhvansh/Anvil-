"""Calibration ledger: log → resolve → score, idempotency, band outcomes, empty summary."""

from __future__ import annotations

import pytest

from oip.calibration.ledger import CalibrationLedger

pytestmark = [pytest.mark.unit]


def test_log_resolve_and_brier(tmp_path):
    led = CalibrationLedger(tmp_path / "cal.duckdb")
    led.log_forecast(forecast_id="f1", underlying="NIFTY", kind="prob_above", prob=0.7,
                     created_ts="2026-06-12T15:30:00+05:30", level_low=22000.0, horizon="1d")
    led.log_forecast(forecast_id="f2", underlying="NIFTY", kind="prob_above", prob=0.3,
                     created_ts="2026-06-12T15:30:00+05:30", level_low=22000.0, horizon="1d")
    assert led.counts("NIFTY") == (2, 0)

    assert led.resolve("f1", realized_value=22100.0, resolved_ts="2026-06-13T15:30:00+05:30") == 1
    assert led.resolve("f2", realized_value=21900.0, resolved_ts="2026-06-13T15:30:00+05:30") == 0
    assert sorted(led.resolved_pairs("NIFTY")) == [(0.3, 0), (0.7, 1)]
    # Brier = ((0.7-1)^2 + (0.3-0)^2) / 2 = (0.09 + 0.09)/2 = 0.09
    assert led.brier("NIFTY") == pytest.approx(0.09)
    assert led.counts("NIFTY") == (2, 2)
    led.close()


def test_relog_is_idempotent(tmp_path):
    led = CalibrationLedger(tmp_path / "cal.duckdb")
    led.log_forecast(forecast_id="f1", underlying="NIFTY", kind="prob_above", prob=0.5,
                     created_ts="t", level_low=1.0)
    led.log_forecast(forecast_id="f1", underlying="NIFTY", kind="prob_above", prob=0.6,
                     created_ts="t", level_low=1.0)
    assert led.counts() == (1, 0)
    led.close()


def test_prob_inside_outcome(tmp_path):
    led = CalibrationLedger(tmp_path / "cal.duckdb")
    led.log_forecast(forecast_id="b1", underlying="NIFTY", kind="prob_inside", prob=0.6,
                     created_ts="t", level_low=21900.0, level_high=22100.0)
    assert led.resolve("b1", realized_value=22000.0, resolved_ts="t2") == 1
    led.log_forecast(forecast_id="b2", underlying="NIFTY", kind="prob_inside", prob=0.6,
                     created_ts="t", level_low=21900.0, level_high=22100.0)
    assert led.resolve("b2", realized_value=22500.0, resolved_ts="t2") == 0
    led.close()


def test_empty_summary(tmp_path):
    led = CalibrationLedger(tmp_path / "cal.duckdb")
    s = led.summary("NIFTY")
    assert s["n_forecasts"] == 0 and s["n_resolved"] == 0
    assert s["brier"] is None
    assert len(s["reliability"]) == 10
    led.close()


def test_invalid_inputs_raise(tmp_path):
    led = CalibrationLedger(tmp_path / "cal.duckdb")
    with pytest.raises(ValueError):
        led.log_forecast(forecast_id="x", underlying="NIFTY", kind="bogus", prob=0.5, created_ts="t")
    with pytest.raises(ValueError):
        led.log_forecast(forecast_id="x", underlying="NIFTY", kind="prob_above", prob=1.5, created_ts="t")
    with pytest.raises(KeyError):
        led.resolve("nope", realized_value=1.0, resolved_ts="t")
    led.close()
