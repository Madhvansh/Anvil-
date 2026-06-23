"""Tests for tips.series.build_series_block (offline-safe time-series assembly)."""

from __future__ import annotations

from anvil.tips import series as S


def test_closes_from_yahoo(monkeypatch):
    monkeypatch.setattr(S.yahoo, "read_cache", lambda sym: [{"c": 100.0 + i} for i in range(10)])
    block = S.build_series_block("NIFTY")
    assert "closes" in block and len(block["closes"]) == 10
    assert block["bars_by_tf"]["1d"] == block["closes"]   # daily fallback timeframe
    assert "flow_series" not in block                     # no snap_store supplied


class _BarStore:
    def closes(self, sym, tf, n=None):
        return {"1h": [1.0, 2.0, 3.0], "5m": [9.0]}.get(tf, [])


def test_with_bar_store(monkeypatch):
    monkeypatch.setattr(S.yahoo, "read_cache", lambda sym: [{"c": float(i)} for i in range(5)])
    block = S.build_series_block("NIFTY", bar_store=_BarStore(), tfs=("1h", "5m"))
    assert block["bars_by_tf"]["1h"] == [1.0, 2.0, 3.0]
    assert "5m" not in block["bars_by_tf"]                # < 2 observations → dropped
    assert "1d" in block["bars_by_tf"]                    # filled from yahoo closes


class _SnapStore:
    def latest(self, u, n):
        return [("t2", 0, 200.0, 0, "x"), ("t1", 0, 100.0, 0, "x")]   # latest() is DESC

    def iv_history(self, u):
        return [0.10, 0.20, 0.30]


def test_with_snap_store_flow(monkeypatch):
    monkeypatch.setattr(S.yahoo, "read_cache", lambda sym: [])
    block = S.build_series_block("NIFTY", snap_store=_SnapStore())
    assert block["flow_series"]["gex_series"] == [100.0, 200.0]      # reversed to ascending
    assert block["flow_series"]["iv_rank_series"] == [0.10, 0.20, 0.30]


def test_empty_when_no_sources(monkeypatch):
    monkeypatch.setattr(S.yahoo, "read_cache", lambda sym: [])
    assert S.build_series_block("NIFTY") == {}
