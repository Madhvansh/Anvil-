"""Wave 4 — single-stock option chains via Upstox (instrument-master key fallback). Network-free."""

from __future__ import annotations

import pytest

from anvil.ingest import instruments as inst
from anvil.ingest.upstox import UpstoxConnector
from anvil.models import OptionType

STOCK_KEY = "NSE_EQ|INE002A01018"

CONTRACT_PAYLOAD = {"data": [{"expiry": "2026-06-25"}, {"expiry": "2026-07-30"}]}
CHAIN_PAYLOAD = {"data": [{
    "strike_price": 1400, "underlying_spot_price": 1410,
    "call_options": {"market_data": {"ltp": 30, "oi": 1000, "prev_oi": 900, "volume": 500,
                                     "bid_price": 29, "ask_price": 31},
                     "option_greeks": {"iv": 22.0, "delta": 0.5}},
    "put_options": {"market_data": {"ltp": 20, "oi": 1200, "prev_oi": 1100, "volume": 400,
                                    "bid_price": 19, "ask_price": 21},
                    "option_greeks": {"iv": 24.0, "delta": -0.5}},
}]}


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _Client:
    def get(self, url, params=None):
        if "option/contract" in url:
            return _Resp(CONTRACT_PAYLOAD)
        if "option/chain" in url:
            return _Resp(CHAIN_PAYLOAD)
        return _Resp({"data": []})


def _conn():
    c = UpstoxConnector("faketoken")
    c._client = _Client()
    return c


def _install_master():
    inst.set_master(inst.InstrumentMaster(
        lot_by_name={"RELIANCE": 250}, key_by_symbol={"RELIANCE": STOCK_KEY}))


def test_stock_instrument_key_fallback():
    _install_master()
    try:
        assert _conn()._instrument_key("RELIANCE") == STOCK_KEY
        with pytest.raises(ValueError):
            _conn()._instrument_key("ZZZZ")
        assert _conn()._instrument_key("NIFTY") == "NSE_INDEX|Nifty 50"   # index map still wins
    finally:
        inst.set_master(inst.InstrumentMaster())


def test_stock_get_expiries():
    _install_master()
    try:
        assert _conn().get_expiries("RELIANCE") == ["2026-06-25", "2026-07-30"]
    finally:
        inst.set_master(inst.InstrumentMaster())


def test_stock_get_chain_uses_master_lot_and_parses():
    _install_master()
    try:
        ch = _conn().get_chain("RELIANCE")          # expiry None → first expiry
        assert ch.underlying == "RELIANCE" and ch.expiry == "2026-06-25"
        assert ch.lot_size == 250 and ch.spot == 1410
        assert len(ch.rows) == 2
        call = next(r for r in ch.rows if r.option_type == OptionType.CALL)
        assert abs(call.iv - 0.22) < 1e-9 and call.oi == 1000 and call.oi_change == 100
    finally:
        inst.set_master(inst.InstrumentMaster())
