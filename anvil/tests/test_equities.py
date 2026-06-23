"""Single-stock equities engine: the cross-sectional model separates a clean up-trend (BUY) from a
down-trend (SELL), projects each into the SAME Tip object (one EQ leg, target/stop, calibratable
conviction), and the backtest resolves held-to-horizon on the realized cash close and writes a
pooled validation cell. No look-ahead: ranking uses only closes ≤ the as-of day."""

from __future__ import annotations

import tempfile
from datetime import date, timedelta

from anvil.backtest.data import BhavcopyArchive
from anvil.ingest.bhavcopy import BhavRow
from anvil.ledger.ledger import CalibrationLedger
from anvil.strategy.types import BEARISH, BULLISH
from anvil.tips.equities import (
    EQUITY_POOL,
    EQUITY_STRUCTURE,
    equity_tips_as_of,
    rank_universe,
    run_equity_backtest,
)
from anvil.tips.store import TipValidationStore


def _fut_row(sym: str, px: float) -> BhavRow:
    return BhavRow(symbol=sym, is_option=False, is_future=True, expiry="2099-01-01", strike=None,
                   option_type=None, settle=px, close=px, oi=10000.0, oi_change=120.0, volume=5000.0,
                   underlying_price=px, lot_size=250)


def _archive(n_days: int = 24):
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(n_days)]
    rows_by_date: dict[str, list[BhavRow]] = {}
    for i, d in enumerate(days):
        rows_by_date[d.isoformat()] = [
            _fut_row("UPSTOCK", 100.0 + i * 2.0),     # clean up-trend
            _fut_row("DOWNSTOCK", 240.0 - i * 2.0),   # clean down-trend
        ]
    return BhavcopyArchive(rows_by_date=rows_by_date), days


def test_rank_separates_uptrend_from_downtrend():
    arch, days = _archive()
    longs, shorts = rank_universe(arch, ["UPSTOCK", "DOWNSTOCK"], days[-1], top_k=5)
    assert any(s[0] == "UPSTOCK" and s[1] == BULLISH for s in longs)
    assert any(s[0] == "DOWNSTOCK" and s[1] == BEARISH for s in shorts)


def test_equity_tip_shape():
    arch, days = _archive()
    tips = equity_tips_as_of(arch, days[-1], equity=1_000_000.0)
    assert tips
    up = next(t for t in tips if t.underlying == "UPSTOCK")
    d = up.to_dict()
    assert d["structure"] == EQUITY_STRUCTURE
    assert d["direction"] == BULLISH
    assert d["legs"][0]["instrument_type"] == "EQ" and d["legs"][0]["side"] == "BUY"
    assert d["target"] and d["stop"] and d["target"] > d["stop"]  # long: target above stop
    assert 0.0 < d["conviction"] <= 0.62  # honest cap


def test_equity_backtest_writes_pooled_cell():
    arch, _days = _archive()
    with tempfile.TemporaryDirectory() as td:
        led = CalibrationLedger(f"{td}/l.duckdb")
        store = TipValidationStore(f"{td}/tv.duckdb")
        try:
            res = run_equity_backtest(arch, ["UPSTOCK", "DOWNSTOCK"], led, store,
                                      min_samples=5, horizon=3, top_k=5)
            assert res["recorded"] > 0 and res["resolved"] > 0
            pooled = store.get(EQUITY_STRUCTURE, "xs_momentum", EQUITY_POOL)
            assert pooled is not None and pooled["n"] > 0
        finally:
            led.close()
            store.close()
