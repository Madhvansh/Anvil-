"""Tests for the spot-tick → OHLC bar aggregator."""

from __future__ import annotations

from anvil.live.bar_aggregator import aggregate_ticks, build_bars_from_snapshots
from anvil.store.bars import BarStore


def _ticks():
    # six 10-second spot ticks spanning two 1-minute buckets
    return [
        ("2026-06-23T09:15:00+05:30", 100.0),
        ("2026-06-23T09:15:20+05:30", 101.5),
        ("2026-06-23T09:15:40+05:30", 100.8),
        ("2026-06-23T09:16:00+05:30", 100.9),
        ("2026-06-23T09:16:30+05:30", 99.5),
        ("2026-06-23T09:16:50+05:30", 102.0),
    ]


def test_aggregate_ticks_ohlc():
    bars = aggregate_ticks(_ticks(), "NIFTY", "1m")
    assert len(bars) == 2
    assert bars[0].open == 100.0 and bars[0].high == 101.5 and bars[0].low == 100.0 and bars[0].close == 100.8
    assert bars[1].open == 100.9 and bars[1].high == 102.0 and bars[1].low == 99.5 and bars[1].close == 102.0
    assert all(b.tf == "1m" for b in bars)


def test_aggregate_ticks_five_min_bucket():
    bars = aggregate_ticks(_ticks(), "NIFTY", "5m")
    assert len(bars) == 1
    assert bars[0].open == 100.0 and bars[0].close == 102.0 and bars[0].high == 102.0 and bars[0].low == 99.5


def test_aggregate_ticks_empty_and_none_price():
    assert aggregate_ticks([], "NIFTY", "1m") == []
    assert aggregate_ticks([("2026-06-23T09:15:00+05:30", None)], "NIFTY", "1m") == []


class _StubSnap:
    def __init__(self, ticks):
        self._t = ticks

    def spot_series(self, symbol):
        return self._t

    def close(self):
        pass


def test_build_bars_from_snapshots(tmp_path):
    bar_store = BarStore(str(tmp_path / "bars.duckdb"))
    try:
        out = build_bars_from_snapshots("NIFTY", ("1m", "5m"), snap_store=_StubSnap(_ticks()), bar_store=bar_store)
        assert out["ticks"] == 6
        assert out["by_tf"]["1m"] == 2 and out["by_tf"]["5m"] == 1
        assert bar_store.count("NIFTY") == 3
        assert bar_store.closes("NIFTY", "1m") == [100.8, 102.0]
    finally:
        bar_store.close()
