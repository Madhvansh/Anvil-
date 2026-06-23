"""Tests for candle_cache (fetch→BarStore, degrade-to-stored, never raise)."""

from __future__ import annotations

from anvil.ingest.candle_cache import fetch_candles
from anvil.models import Bar
from anvil.store.bars import BarStore


class _FakeConn:
    """Returns one bar per tf; can be told to raise for a given tf."""

    def __init__(self, raise_tf=None):
        self.raise_tf = raise_tf

    def get_candles(self, symbol, tf, *, from_date=None, to_date=None, intraday=False):
        if tf == self.raise_tf:
            raise RuntimeError("boom")
        return [Bar(symbol=symbol.upper(), tf=tf, ts=f"2026-06-23T09:15:00+05:30|{tf}",
                    open=100, high=101, low=99, close=100.5, volume=10)]


def test_fetch_candles_writes_each_tf(tmp_path):
    store = BarStore(str(tmp_path / "bars.duckdb"))
    try:
        out = fetch_candles(_FakeConn(), "NIFTY", ("1d", "1h", "5m"), store=store)
        assert out["symbol"] == "NIFTY"
        assert out["by_tf"] == {"1d": 1, "1h": 1, "5m": 1}
        assert out["stored"]["1d"] == 1
        assert not out["errors"]
        assert store.count("NIFTY") == 3
    finally:
        store.close()


def test_fetch_candles_degrades_on_error(tmp_path):
    store = BarStore(str(tmp_path / "bars.duckdb"))
    try:
        out = fetch_candles(_FakeConn(raise_tf="1h"), "NIFTY", ("1d", "1h"), store=store)
        assert out["by_tf"]["1d"] == 1 and out["by_tf"]["1h"] == 0
        assert "1h" in out["errors"] and "boom" in out["errors"]["1h"]
        assert store.count("NIFTY") == 1                      # the good tf still persisted
    finally:
        store.close()
