"""The Calibration Score: an honest, intuitive headline derived from ECE — NOT an accuracy or
guaranteed-return claim. It must degrade honestly (no fake number) below a minimum sample size,
and be computed independently per source class.
"""

from anvil.ledger.ledger import (
    KIND_PROB_ABOVE,
    MIN_SAMPLES_FOR_SCORE,
    CalibrationLedger,
    Forecast,
    calibration_score,
)


def test_none_below_min_samples():
    s = calibration_score(0.05, MIN_SAMPLES_FOR_SCORE - 1)
    assert s["score"] is None
    assert s["rating"] == "insufficient data"
    assert str(MIN_SAMPLES_FOR_SCORE) in s["reading"]


def test_perfect_calibration_scores_100():
    s = calibration_score(0.0, 100)
    assert s["score"] == 100
    assert s["rating"] == "well calibrated"


def test_biased_scores_below_calibrated():
    good = calibration_score(0.02, 100)["score"]
    bad = calibration_score(0.30, 100)["score"]
    assert good > bad


def test_nan_and_out_of_range_ece_are_safe():
    assert calibration_score(float("nan"), 100)["score"] is None
    assert 0 <= calibration_score(1.5, 100)["score"] <= 100  # ECE>1 clamps to 0, never negative


def _well_calibrated_history(led, source, n_per_bin=10):
    seq = 0
    for b in range(10):
        p = (b + 0.5) / 10.0
        ones = round(p * n_per_bin)
        for j in range(n_per_bin):
            event = 1 if j < ones else 0
            f = Forecast(
                underlying="NIFTY", created_ts="2026-01-01T00:00:00+00:00", resolve_ts="2026-01-08",
                kind=KIND_PROB_ABOVE, params={"level": 100.0, "seq": seq}, prob=p,
                spot=100.0, forward=100.0, source=source,
            )
            led.record(f)
            led.resolve(f.id, realized_value=101.0 if event else 99.0)
            seq += 1


def test_score_is_computed_per_class(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    _well_calibrated_history(led, source="backtest")     # 100 real backtest forecasts
    by = led.metrics_by_class()
    assert by["backtest"]["calibration_score"]["score"] is not None
    assert by["backtest"]["calibration_score"]["n"] == 100
    # No live forecasts yet → live score honestly reports insufficient data, independently.
    assert by["live"]["calibration_score"]["score"] is None
    led.close()
