"""Unit tests for the multi-timeframe momentum engine (pure-numpy, hand-verifiable)."""

from __future__ import annotations

import numpy as np
import pytest

from anvil.engine import momentum as m
from anvil.strategy.types import BULLISH, NEUTRAL


# --- primitives ------------------------------------------------------------- #
def test_roc_basic_and_abstain():
    assert m.roc([100.0, 110.0], 1) == pytest.approx(0.1)
    assert m.roc([100.0, 110.0, 121.0], 2) == pytest.approx(0.21)
    assert m.roc([100.0], 1) is None          # too short → abstain
    assert m.roc([0.0, 110.0], 1) is None     # non-positive base → abstain


def test_sma_and_ema():
    assert m.sma([1, 2, 3, 4], 2) == 3.5
    assert m.sma([1, 2], 5) is None
    # span=1 → alpha=1 → EMA collapses to the last value.
    assert m.ema([1.0, 2.0, 3.0], span=1) == 3.0


def test_rsi_extremes():
    up = list(range(1, 30))            # strictly increasing
    down = list(range(30, 1, -1))      # strictly decreasing
    flat = [10.0] * 30
    assert m.rsi(up, 14) == 100.0
    assert m.rsi(down, 14) == 0.0
    assert m.rsi(flat, 14) == 50.0
    assert m.rsi([1, 2, 3], 14) is None  # insufficient


def test_true_range_and_atr():
    high = [10.0, 11.0, 12.0]
    low = [9.0, 9.5, 11.0]
    close = [9.5, 10.5, 11.5]
    tr = m.true_range(high, low, close)
    # bar1: max(11-9.5, |11-9.5|, |9.5-9.5|)=1.5 ; bar2: max(12-11, |12-10.5|, |11-10.5|)=1.5
    assert np.allclose(tr, [1.5, 1.5])
    assert m.atr(high, low, close, n=2) == 1.5


def test_adx_trend_stronger_than_chop():
    n = 5
    bars = 40
    # Clean uptrend.
    up_c = np.linspace(100, 140, bars)
    up_h = up_c + 0.5
    up_l = up_c - 0.5
    # Choppy sawtooth around a flat level.
    idx = np.arange(bars)
    chop_c = 100 + np.where(idx % 2 == 0, 0.5, -0.5)
    chop_h = chop_c + 0.5
    chop_l = chop_c - 0.5
    adx_trend = m.adx(up_h, up_l, up_c, n)
    adx_chop = m.adx(chop_h, chop_l, chop_c, n)
    assert adx_trend is not None and adx_chop is not None
    assert adx_trend > adx_chop
    assert adx_trend > 25.0  # a clean trend reads strong


def test_donchian_vwap_opening_range_gap():
    assert m.donchian([10, 12, 11], [9, 8, 9], 3) == {"upper": 12.0, "lower": 8.0, "mid": 10.0}
    assert m.vwap([10.0, 20.0], [1.0, 3.0]) == 17.5
    assert m.vwap([10.0, 20.0], [0.0, 0.0]) is None
    assert m.opening_range([10, 12, 11], [9, 8, 9], 3) == {"or_high": 12.0, "or_low": 8.0}
    assert m.gap_pct(100.0, 101.0) == pytest.approx(0.01)
    assert m.gap_pct(0.0, 101.0) is None


def test_autocorr_sign():
    # Persistent regimes (a positive run then a negative run) → positive lag-1 autocorrelation.
    trending = [0.01, 0.01, 0.01, -0.01, -0.01, -0.01]
    assert m.autocorr(trending, 1) > 0
    alternating = [0.01, -0.01, 0.01, -0.01, 0.01, -0.01]
    assert m.autocorr(alternating, 1) < 0
    assert m.autocorr([0.01], 1) is None


# --- time-series momentum --------------------------------------------------- #
def test_time_series_momentum_uptrend():
    closes = list(np.linspace(100, 130, 80))
    tsm = m.time_series_momentum(closes, lookbacks=(5, 21, 63))
    assert tsm is not None
    for lb, d in tsm.items():
        assert d["score"] is None or d["score"] > 0   # clean uptrend → positive trend score
        assert d["roc"] > 0
    assert m.time_series_momentum([100, 101], lookbacks=(63,)) is None  # all lookbacks too long


# --- multi-timeframe consensus --------------------------------------------- #
def test_multi_timeframe_consensus_bullish():
    up = list(np.linspace(100, 140, 60))
    read = m.multi_timeframe_momentum({"5m": up, "1h": up, "1d": up})
    assert read.direction == BULLISH
    assert read.strength > 0
    assert read.agreement == 3
    assert read.n_timeframes == 3


def test_multi_timeframe_conflict_abstains():
    up = list(np.linspace(100, 140, 60))
    down = list(np.linspace(140, 100, 60))
    read = m.multi_timeframe_momentum({"1h": up, "1d": down})
    assert read.direction == NEUTRAL
    assert read.strength == 0.0


def test_multi_timeframe_no_data_abstains():
    read = m.multi_timeframe_momentum({"1d": [100, 101]})
    assert read.direction == NEUTRAL
    assert read.note in ("no_timeframe_fired", "consensus", "timeframes_conflict")
    assert read.strength == 0.0


# --- cross-sectional -------------------------------------------------------- #
def test_cross_sectional_rank():
    out = m.cross_sectional_rank({"A": 0.10, "B": 0.20, "C": -0.10})
    assert out["B"]["percentile"] == 1.0 and out["B"]["rank"] == 1
    assert out["C"]["percentile"] == 0.0 and out["C"]["rank"] == 3
    assert m.cross_sectional_rank({}) == {}


# --- intraday mechanics ----------------------------------------------------- #
def test_or_breakout():
    highs = [10.0, 10.5, 10.2, 11.0]
    lows = [9.5, 9.8, 9.7, 10.5]
    up = m.or_breakout(highs, lows, last_price=10.8, first_n=3)
    assert up["fired"] and up["direction"] == BULLISH and up["strength"] > 0
    inside = m.or_breakout(highs, lows, last_price=10.0, first_n=3)
    assert not inside["fired"] and inside["direction"] == NEUTRAL


def test_vwap_reversion():
    out = m.vwap_reversion([10.0, 20.0], [1.0, 3.0], last_price=18.0)
    assert out["vwap"] == 17.5 and out["above"] is True
    assert abs(out["distance"] - (18.0 / 17.5 - 1.0)) < 1e-9


def test_last30_expiry_gamma_drift():
    # Negative gamma + near expiry + positive rest-of-day → bullish drift fires.
    rets = [0.002, 0.001, 0.0005]
    fired = m.last30_expiry_gamma_drift(rets, gex_sign=-1, days_to_expiry=0)
    assert fired["fired"] and fired["direction"] == BULLISH
    # Positive gamma → no Baltussen amplification → not fired.
    not_fired = m.last30_expiry_gamma_drift(rets, gex_sign=1, days_to_expiry=0)
    assert not not_fired["fired"] and not_fired["direction"] == NEUTRAL
    assert m.last30_expiry_gamma_drift([0.001], gex_sign=-1) is None
