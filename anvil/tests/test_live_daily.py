"""Live daily loop: records forward forecasts under the right source class, idempotent, and
resolves due forecasts. Uses the offline DemoConnector so it runs with no credentials."""

from anvil.ingest.demo import DemoConnector
from anvil.ledger.ledger import CalibrationLedger
from anvil.live.daily import run_daily


def test_records_under_live_source(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    res = run_daily(["NIFTY"], connector=DemoConnector(), ledger=led, source="upstox")
    assert res["recorded"]["NIFTY"] == 3
    assert led.metrics(classes=("live",))["pending_count"] == 3   # logged as a real (live) forecast
    led.close()


def test_demo_source_is_excluded_from_public(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    run_daily(["NIFTY"], connector=DemoConnector(), ledger=led)   # source defaults to conn.name='demo'
    assert led.metrics()["pending_count"] == 0                    # excluded from the public curve
    assert led.metrics(classes=("demo",))["pending_count"] == 3   # present, but only in the demo class
    led.close()


def test_run_daily_is_idempotent_same_day(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    run_daily(["NIFTY"], connector=DemoConnector(), ledger=led, source="upstox")
    run_daily(["NIFTY"], connector=DemoConnector(), ledger=led, source="upstox")
    assert led.metrics(classes=("live",))["pending_count"] == 3   # no duplicate forecasts
    led.close()


def test_run_daily_resolves_due(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    conn = DemoConnector()
    spot = conn.get_chain("NIFTY").spot
    run_daily(["NIFTY"], connector=conn, ledger=led, source="upstox")
    res = run_daily(
        ["NIFTY"], connector=conn, ledger=led, source="upstox",
        realized={"NIFTY": spot}, as_of="2099-01-01T00:00:00+00:00",
    )
    assert res["resolved"]["NIFTY"] >= 1
    assert led.metrics(classes=("live",))["resolved_count"] >= 1
    led.close()
