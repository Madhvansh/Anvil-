"""Tests for the multi-timeframe BarStore + the OHLCV resampler."""

from __future__ import annotations

from anvil.models import Bar
from anvil.store.bars import BarStore, resample_bars


def _bar(ts, o, h, lo, c, v=100.0, tf="1m", symbol="NIFTY"):
    return Bar(symbol=symbol, tf=tf, ts=ts, open=o, high=h, low=lo, close=c, volume=v)


def _minute_bars():
    base = "2026-06-23T09:1{}:00+05:30"
    # five 1-minute bars 09:15..09:19
    return [
        _bar(base.format(5), 100, 101, 99, 100.5, 10),
        _bar(base.format(6), 100.5, 102, 100, 101, 12),
        _bar(base.format(7), 101, 101.5, 100.5, 101.2, 8),
        _bar(base.format(8), 101.2, 103, 101, 102.8, 20),
        _bar(base.format(9), 102.8, 103.5, 102, 103, 15),
    ]


def test_resample_1m_to_5m():
    out = resample_bars(_minute_bars(), "5m")
    assert len(out) == 1
    b = out[0]
    assert b.tf == "5m"
    assert b.open == 100 and b.close == 103
    assert b.high == 103.5 and b.low == 99
    assert b.volume == 10 + 12 + 8 + 20 + 15


def test_resample_two_buckets_and_daily():
    bars = _minute_bars()
    bars.append(_bar("2026-06-23T09:20:00+05:30", 103, 104, 102.5, 103.8, 5))
    out = resample_bars(bars, "5m")
    assert len(out) == 2 and out[1].open == 103 and out[1].close == 103.8
    day = resample_bars(bars, "1d")
    assert len(day) == 1 and day[0].tf == "1d"
    assert day[0].open == 100 and day[0].close == 103.8 and day[0].high == 104


def test_bar_store_write_read_idempotent(tmp_path):
    store = BarStore(str(tmp_path / "bars.duckdb"))
    try:
        store.write_bars(_minute_bars())
        assert store.count("NIFTY") == 5
        got = store.bars("NIFTY", "1m")
        assert len(got) == 5 and got[0].close == 100.5
        assert store.closes("NIFTY", "1m", n=2) == [102.8, 103.0]
        assert store.latest_ts("NIFTY", "1m") == "2026-06-23T09:19:00+05:30"
        # Re-write the same bar with a different close → update in place (no duplicate).
        store.write_bars([_bar("2026-06-23T09:19:00+05:30", 102.8, 104, 102, 103.9, 99)])
        assert store.count("NIFTY") == 5
        assert store.bars("NIFTY", "1m")[-1].close == 103.9
    finally:
        store.close()


def test_bar_store_since_filter(tmp_path):
    store = BarStore(str(tmp_path / "bars.duckdb"))
    try:
        store.write_bars(_minute_bars())
        recent = store.bars("NIFTY", "1m", since="2026-06-23T09:18:00+05:30")
        assert len(recent) == 2
    finally:
        store.close()


def test_resample_empty():
    assert resample_bars([], "5m") == []
