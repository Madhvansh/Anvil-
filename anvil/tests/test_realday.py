"""Today / real-day replay: RealDaySource reprices the real intraday path off the held smile, and
run_today grades its predictions while keeping demo/paper out of the public calibration curve."""

from __future__ import annotations

import tempfile

from anvil.engine.util import year_fraction
from anvil.ingest.demo import DemoConnector
from anvil.ledger.ledger import CalibrationLedger
from anvil.live.realday import run_today
from anvil.live.realday_source import RealDaySource
from anvil.live.realtime import RealtimeEngine
from anvil.paper.account import PaperBook


def test_realday_source_reprices_along_path():
    src = RealDaySource("NIFTY", DemoConnector(), interval_min=30)
    ts = src.timestamps()
    assert len(ts) >= 3
    c0 = src.chain(ts[0], 0)
    cN = src.chain(ts[-1], len(ts) - 1)
    assert c0.rows and cN.rows
    assert c0.spot == src.spot_at(0) and cN.spot == src.spot_at(len(ts) - 1)
    assert c0.future_price_source == "realday_smile_held"
    assert all((r.ltp or 0) > 0 for r in c0.rows)  # every leg priced
    # Time-to-expiry decays across the day.
    assert year_fraction(cN.expiry, ts[-1]) < year_fraction(c0.expiry, ts[0])


def test_realday_chain_monotonic_in_spot():
    src = RealDaySource("NIFTY", DemoConnector(), interval_min=30)
    ts = src.timestamps()[0]
    # Force two chains at the same timestamp but different spots via the candle path.
    src.candles = [(ts, 1.0, 1.0, 1.0, 24000.0), (ts, 1.0, 1.0, 1.0, 24300.0)]
    a, b = src.chain(ts, 0), src.chain(ts, 1)
    k = a.atm_strike()
    call_a = next(r for r in a.rows if r.option_type.value == "CE" and r.strike == k)
    call_b = next(r for r in b.rows if r.option_type.value == "CE" and r.strike == k)
    assert (call_b.ltp or 0) > (call_a.ltp or 0)  # higher spot lifts the call


def test_run_today_grades_and_isolates_demo():
    ledger = CalibrationLedger(tempfile.mktemp(suffix=".duckdb"))
    eng = RealtimeEngine(book=PaperBook(starting_capital=1_000_000.0), ledger=ledger)
    eng, rep = run_today(eng, ["NIFTY"], DemoConnector(), ledger=ledger, interval_min=30)
    assert rep["meta"]["mode"] == "today"
    assert rep["equity_curve"]
    sc = rep["prediction_scorecard"]["NIFTY"]
    assert {"band_1sigma", "realized_close", "brier"} <= set(sc)
    assert set(sc["hits"]) == {"in_1sigma", "in_half_sigma", "above_open"}
    # Credible intraday band (ATM-IV based, not the inflated RND std): well under ±2%.
    width = sc["band_1sigma"][1] - sc["band_1sigma"][0]
    assert 0 < width < 0.04 * sc["open"]
    # Moat isolation: a demo-degraded run NEVER enters the public (live) curve.
    assert ledger.metrics(classes=("live",))["resolved_count"] == 0
    assert ledger.metrics(classes=("demo",))["resolved_count"] >= 3
    ledger.close()
