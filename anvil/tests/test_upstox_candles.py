"""Tests for Upstox candle parsing / fetch / resample / key resolution (network-free via a fake client)."""

from __future__ import annotations

import pytest

from anvil.ingest import instruments as inst
from anvil.ingest.upstox import UpstoxConnector
from anvil.models import Bar

FAKE = {"data": {"candles": [
    ["2026-06-23T15:29:00+05:30", 100, 102, 99, 101, 5000, 12345],
    ["2026-06-23T15:28:00+05:30", 99, 101, 98, 100, 4000, 12000],
]}}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Client:
    def __init__(self, payload):
        self._p = payload
        self.last_url = None

    def get(self, url):
        self.last_url = url
        return _Resp(self._p)


def _conn(payload):
    c = UpstoxConnector("faketoken")
    c._client = _Client(payload)
    return c


def test_parse_candles_orders_and_fields():
    bars = UpstoxConnector._parse_candles(FAKE["data"]["candles"], "NIFTY", "1m")
    assert len(bars) == 2
    assert bars[0].ts < bars[1].ts                 # newest-first input → ascending output
    assert bars[0].open == 99 and bars[1].close == 101
    assert bars[1].volume == 5000 and bars[1].oi == 12345


def test_get_candles_native_1m_builds_url():
    c = _conn(FAKE)
    bars = c.get_candles("NIFTY", "1m", from_date="2026-06-01", to_date="2026-06-23")
    assert len(bars) == 2 and all(isinstance(b, Bar) for b in bars)
    assert "1minute" in c._client.last_url and "NSE_INDEX" in c._client.last_url


def test_get_candles_derived_resamples_to_5m():
    candles = [[f"2026-06-23T09:1{mm}:00+05:30", 100 + mm, 101 + mm, 99 + mm, 100 + mm, 10, 0]
               for mm in range(5, 10)]
    c = _conn({"data": {"candles": candles}})
    bars = c.get_candles("NIFTY", "5m")
    assert len(bars) == 1 and bars[0].tf == "5m"


def test_get_historical_candles_tuple_shape():
    c = _conn(FAKE)
    out = c.get_historical_candles("NIFTY", interval_min=1)
    assert out and len(out[0]) == 5


def test_resolve_candle_key_index_equity_unknown():
    c = _conn(FAKE)
    assert "NSE_INDEX" in c._resolve_candle_key("NIFTY")
    inst.set_master(inst.InstrumentMaster(key_by_symbol={"RELIANCE": "NSE_EQ|INE002A01018"}))
    try:
        assert c._resolve_candle_key("RELIANCE") == "NSE_EQ|INE002A01018"
        with pytest.raises(ValueError):
            c._resolve_candle_key("NOSUCHSYM")
    finally:
        inst.set_master(inst.InstrumentMaster())  # reset process-wide master
