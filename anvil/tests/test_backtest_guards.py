"""Backtester bias guards as FAILING tests (hard rail), plus a real out-of-sample curve.

If any guard regresses — look-ahead, survivorship, or expiry-date resolution — these tests
fail the build. The reliability curve is the product's only asset; its integrity is enforced
here, not asserted in prose.
"""

from datetime import date
from pathlib import Path

import pytest

from anvil.backtest import AsOfContext, BhavcopyArchive, LookAheadError, run_backtest
from anvil.backtest.asof import SurvivorshipError, assert_all_liquid
from anvil.ledger.ledger import CalibrationLedger
from anvil.models import ChainRow, OptionChain, OptionType

FIX = (Path(__file__).parent / "fixtures" / "bhavcopy_fo_sample.csv").read_text()


def _archive_2day(realized: float = 24300.0) -> BhavcopyArchive:
    """Day 1 = a real chain (expiry 2026-06-26); day 2 = the expiry day (empty F&O, but a
    realized index close to settle against)."""
    return BhavcopyArchive.from_csv_texts(
        {"2026-06-12": FIX, "2026-06-26": ""},
        index_close={"2026-06-12": {"NIFTY": 24010.0}, "2026-06-26": {"NIFTY": realized}},
    )


class _FakeArchive:
    """Returns hand-built chains regardless of date — to exercise the guards directly."""

    def __init__(self, chains):
        self._chains = chains

    def chains_on(self, d):
        return self._chains

    def index_close_on(self, d, u):
        return None


def _chain(ts: str, expiry: str) -> OptionChain:
    rows = [
        ChainRow(strike=24000 + 100 * i, option_type=OptionType.CALL, ltp=100.0, oi=1000, volume=10)
        for i in range(5)
    ]
    return OptionChain(
        underlying="NIFTY", spot=24000.0, expiry=expiry, timestamp=ts, rows=rows,
        future_price=24000.0, future_price_source="test",
    )


# ---- look-ahead guards (must RAISE) ----
def test_future_dated_chain_raises_lookahead():
    ctx = AsOfContext(date(2026, 6, 12), _FakeArchive([_chain("2026-06-15T15:30:00+05:30", "2026-06-26")]))
    with pytest.raises(LookAheadError):
        ctx.open_chains("NIFTY")


def test_cannot_forecast_already_expired_expiry():
    ctx = AsOfContext(date(2026, 6, 26), _FakeArchive([_chain("2026-06-26T15:30:00+05:30", "2026-06-26")]))
    with pytest.raises(LookAheadError):
        ctx.open_chains("NIFTY")


# ---- survivorship ----
def test_zero_liquidity_strike_excluded():
    ctx = AsOfContext(date(2026, 6, 12), _archive_2day())
    chains = ctx.open_chains("NIFTY")
    assert len(chains) == 1
    assert 26000 not in chains[0].strikes()   # phantom oi=0/vol=0 strike dropped
    assert_all_liquid(chains[0])               # survivors are all genuinely traded


def test_assert_all_liquid_raises_on_dead_strike():
    dead = OptionChain(
        underlying="NIFTY", spot=24000.0, expiry="2026-06-26", timestamp="2026-06-12T15:30:00+05:30",
        rows=[ChainRow(strike=99999, option_type=OptionType.CALL, ltp=0.05, oi=0, volume=0)],
    )
    with pytest.raises(SurvivorshipError):
        assert_all_liquid(dead)


# ---- end-to-end: a real, out-of-sample curve ----
def test_backtest_produces_real_oos_curve(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "bt.duckdb"))
    res = run_backtest(_archive_2day(), ["NIFTY"], led, source="backtest")
    assert res["recorded"] == 3        # 1σ band, 0.5σ band, prob_above
    m = res["metrics"]
    assert m["resolved_count"] == 3
    assert m["source_class_filter"] == ["backtest"]
    led.close()


def test_resolution_uses_expiry_close_not_today(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "bt.duckdb"))
    run_backtest(_archive_2day(realized=25000.0), ["NIFTY"], led, source="backtest")
    rows = led.con.execute(
        "SELECT o.event, o.resolved_ts FROM forecasts f JOIN outcomes o ON f.id=o.forecast_id "
        "WHERE f.kind='prob_above'"
    ).fetchall()
    assert rows and rows[0][0] == 1                       # 25000 >> spot → event 1
    assert rows[0][1].startswith("2026-06-26")            # resolved at expiry, not 'today'
    led.close()


def test_backtest_is_idempotent_on_rerun(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "bt.duckdb"))
    m1 = run_backtest(_archive_2day(), ["NIFTY"], led)["metrics"]
    m2 = run_backtest(_archive_2day(), ["NIFTY"], led)["metrics"]   # rerun, same ledger
    assert m1["resolved_count"] == m2["resolved_count"] == 3
    assert m1["reliability_curve"] == m2["reliability_curve"]       # no dup rows, identical curve
    led.close()
