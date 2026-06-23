"""Tests for engine.constituents (weighted breadth, aggregate strength, lead-lag)."""

from __future__ import annotations

import numpy as np

from anvil.engine import constituents as C


def test_index_weights_known_and_unknown():
    assert C.index_weights("BANKNIFTY")["HDFCBANK"] > 0
    assert C.index_weights("NOPE") == {}


def test_weighted_breadth_bullish():
    w = C.index_weights("BANKNIFTY")
    dirs = {"HDFCBANK": "bullish", "ICICIBANK": "bullish", "SBIN": "bearish",
            "AXISBANK": "neutral", "KOTAKBANK": "bullish"}
    out = C.weighted_breadth(dirs, w)
    assert out["bias"] == "bullish" and out["net_breadth"] > 0.15
    assert 0.0 < out["coverage"] <= 1.0 and out["n"] == 5


def test_weighted_breadth_partial_coverage():
    w = C.index_weights("BANKNIFTY")
    out = C.weighted_breadth({"HDFCBANK": "bearish"}, w)
    assert out["bias"] == "bearish" and out["coverage"] < 0.5 and out["n"] == 1


def test_weighted_breadth_no_overlap_none():
    assert C.weighted_breadth({"ZZZZ": "bullish"}, C.index_weights("BANKNIFTY")) is None


def test_aggregate_strength():
    w = C.index_weights("BANKNIFTY")
    reads = {"HDFCBANK": {"direction": "bullish", "strength": 0.8},
             "ICICIBANK": {"direction": "bullish", "strength": 0.6},
             "SBIN": {"direction": "bearish", "strength": 0.4}}
    out = C.aggregate_strength(reads, w)
    assert out["bias"] == "bullish" and out["signed_strength"] > 0 and out["coverage"] > 0


def test_lead_lag_detects_known_lag():
    rng = np.random.default_rng(0)
    base = rng.standard_normal(60)
    index_ret = base.copy()
    # constituent leads the index by 2 steps: index[t] ≈ constituent[t-2]
    cons_ret = np.zeros(60)
    cons_ret[:-2] = base[2:]
    out = C.lead_lag(index_ret, cons_ret, max_lag=3)
    assert out is not None and out["lead_lag"] == 2 and out["correlation"] > 0.8


def test_lead_lag_too_short_none():
    assert C.lead_lag([0.1, 0.2], [0.1, 0.2], max_lag=3) is None
