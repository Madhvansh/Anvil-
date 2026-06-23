"""Calibration ledger: scoring math, event resolution, record/resolve roundtrip, emit."""

import pytest

from anvil.ledger import scoring
from anvil.ledger.ledger import (
    KIND_PROB_ABOVE,
    KIND_PROB_IN_BAND,
    CalibrationLedger,
    Forecast,
    emit_forecasts,
    event_for,
)


# ---- scoring ----
def test_brier_score():
    assert scoring.brier_score([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1]) == pytest.approx(0.01)
    assert scoring.brier_score([0.5, 0.5], [0, 1]) == pytest.approx(0.25)


def test_reliability_curve_bins():
    rows = scoring.reliability_curve([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1], n_bins=10)
    by_pred = {round(r["predicted_mean"], 1): r for r in rows}
    assert by_pred[0.1]["empirical_freq"] == 0.0 and by_pred[0.1]["count"] == 2
    assert by_pred[0.9]["empirical_freq"] == 1.0 and by_pred[0.9]["count"] == 2


def test_ece_well_calibrated_beats_biased():
    # well-calibrated: predictions match outcomes; biased: overconfident
    good = scoring.expected_calibration_error([0.1, 0.1, 0.9, 0.9], [0, 0, 1, 1])
    bad = scoring.expected_calibration_error([0.9, 0.9, 0.1, 0.1], [0, 0, 1, 1])
    assert good == pytest.approx(0.1, abs=1e-9)
    assert bad > good


def test_coverage():
    c = scoring.coverage([0.68, 0.68, 0.68], [1, 1, 0])
    assert c["nominal"] == pytest.approx(0.68)
    assert c["realized"] == pytest.approx(2 / 3)
    assert c["count"] == 3


# ---- event resolution ----
def test_event_for():
    assert event_for(KIND_PROB_IN_BAND, {"lower": 100, "upper": 110}, 105) == 1
    assert event_for(KIND_PROB_IN_BAND, {"lower": 100, "upper": 110}, 99) == 0
    assert event_for(KIND_PROB_ABOVE, {"level": 100}, 100) == 1
    assert event_for(KIND_PROB_ABOVE, {"level": 100}, 99) == 0


# ---- ledger roundtrip ----
def _fc(prob=0.68, lower=100, upper=110):
    return Forecast(
        underlying="NIFTY", created_ts="2026-06-18T06:00:00+00:00", resolve_ts="2026-06-25",
        kind=KIND_PROB_IN_BAND, params={"lower": lower, "upper": upper, "nominal": "1sigma"},
        prob=prob, spot=105.0, forward=105.5,
    )


def test_record_is_idempotent(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    f = _fc()
    led.record(f)
    led.record(f)  # same id → no-op
    assert len(led.pending("NIFTY")) == 1
    led.close()


def test_record_resolve_metrics(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    f = _fc(prob=0.7)
    led.record(f)
    assert led.metrics()["pending_count"] == 1
    led.resolve(f.id, realized_value=105.0)  # inside [100,110] → event 1
    m = led.metrics()
    assert m["resolved_count"] == 1
    assert m["pending_count"] == 0
    assert m["brier"] == pytest.approx((0.7 - 1) ** 2)
    led.close()


def test_resolve_due(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    led.record(_fc(lower=100, upper=110))
    led.record(Forecast(underlying="NIFTY", created_ts="2026-06-18T06:00:00+00:00",
                        resolve_ts="2026-06-25", kind=KIND_PROB_ABOVE, params={"level": 100},
                        prob=0.6, spot=105.0, forward=105.5))
    n = led.resolve_due("NIFTY", realized_value=108.0, as_of="2026-06-26T00:00:00+00:00")
    assert n == 2
    assert led.metrics()["resolved_count"] == 2
    led.close()


def test_metrics_json_serializable_without_band_forecasts(tmp_path):
    import json

    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    # only prob_above forecasts → band_coverage has no members (must be None, not NaN)
    f = Forecast(underlying="NIFTY", created_ts="2026-06-18T06:00:00+00:00", resolve_ts="2026-06-25",
                 kind=KIND_PROB_ABOVE, params={"level": 100}, prob=0.6, spot=100.0, forward=100.0)
    led.record(f)
    led.resolve(f.id, realized_value=101.0)
    m = led.metrics()
    assert m["band_coverage"]["nominal"] is None
    json.dumps(m)  # must not raise on NaN
    led.close()


def test_emit_forecasts_from_demo():
    from anvil.engine.implied_dist import implied_distribution
    from anvil.ingest.demo import build_demo_chain

    chain = build_demo_chain("NIFTY", spot=24000.0, expiry="2026-07-31",
                             timestamp="2026-06-17T06:00:00+00:00")
    dist = implied_distribution(chain)
    fs = emit_forecasts(chain, dist)
    assert len(fs) == 3
    for f in fs:
        assert 0.0 <= f.prob <= 1.0
        assert f.id  # deterministic id present
    kinds = {f.kind for f in fs}
    assert KIND_PROB_IN_BAND in kinds and KIND_PROB_ABOVE in kinds
