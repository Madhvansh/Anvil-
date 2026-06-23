"""Hard rail: synthetic (seed) and synthetic-but-live (demo) forecasts must NEVER appear in
the public reliability curve. This is the single mistake that would destroy the product's only
asset, so it is locked by tests that fail the build if the guarantee regresses.
"""

from anvil.ledger.ledger import (
    KIND_PROB_ABOVE,
    PUBLIC_CLASSES,
    CalibrationLedger,
    Forecast,
    source_class,
)


def _record_resolved(led, *, source, prob, event, seq):
    f = Forecast(
        underlying="NIFTY", created_ts="2026-06-18T06:00:00+00:00", resolve_ts="2026-06-25",
        kind=KIND_PROB_ABOVE, params={"level": 100.0, "seq": seq}, prob=prob,
        spot=100.0, forward=100.0, source=source,
    )
    led.record(f)
    led.resolve(f.id, realized_value=101.0 if event else 99.0)
    return f


def _bulk(led, n, source):
    for i in range(n):
        _record_resolved(led, source=source, prob=0.5, event=i % 2, seq=i)


def test_seed_never_in_public_metrics(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    _bulk(led, 100, source="seed")                       # synthetic
    _record_resolved(led, source="backtest", prob=0.9, event=1, seq=10_001)  # one real row
    m = led.metrics()                                    # default = PUBLIC_CLASSES
    assert m["resolved_count"] == 1                      # only the backtest row is public
    assert m["counts_by_class"]["seed"] == 100           # the seed exists in the DB…
    assert m["counts_by_class"]["backtest"] == 1         # …but is excluded from the curve
    led.close()


def test_default_excludes_demo(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    _bulk(led, 10, source="demo")
    m = led.metrics()
    assert m["resolved_count"] == 0
    assert m["counts_by_class"].get("demo") == 10
    led.close()


def test_synthetic_visible_only_when_explicitly_requested(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    _bulk(led, 20, source="seed")
    assert led.metrics(classes=("seed",))["resolved_count"] == 20   # opt-in, internal/QA only
    assert led.metrics()["resolved_count"] == 0                     # never on the default path
    led.close()


def test_source_class_map_is_total_and_correct():
    for s in ("anvil", "upstox", "dhan", "groww", "kite", "backtest", "seed", "demo", None, ""):
        assert source_class(s) in ("seed", "backtest", "live", "demo")
    assert source_class("upstox") == "live"      # any real connector → live
    assert source_class("anvil") == "live"
    assert source_class("demo") == "demo"        # synthetic-but-live → excluded
    assert source_class("seed") == "seed"        # synthetic → excluded
    assert source_class("backtest") == "backtest"


def test_metrics_by_class_separates_backtest_and_live(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    _record_resolved(led, source="backtest", prob=0.8, event=1, seq=1)
    _record_resolved(led, source="upstox", prob=0.7, event=1, seq=2)
    by = led.metrics_by_class()
    assert set(by) == set(PUBLIC_CLASSES)
    assert by["backtest"]["resolved_count"] == 1
    assert by["live"]["resolved_count"] == 1
    led.close()
