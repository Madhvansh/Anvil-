"""Tests for instrument-master key + option resolution from an Upstox dump."""

from __future__ import annotations

from anvil.ingest.instruments import InstrumentMaster

DUMP = [
    {"segment": "NSE_INDEX", "instrument_key": "NSE_INDEX|Nifty 50",
     "trading_symbol": "NIFTY 50", "name": "NIFTY"},
    {"segment": "NSE_EQ", "instrument_key": "NSE_EQ|INE002A01018",
     "trading_symbol": "RELIANCE", "name": "RELIANCE", "lot_size": 1},
    {"segment": "NSE_FO", "instrument_key": "NSE_FO|opt1", "trading_symbol": "RELIANCE 1400 CE",
     "underlying_symbol": "RELIANCE", "instrument_type": "CE", "strike_price": 1400,
     "expiry": "2026-06-25", "lot_size": 250, "name": "RELIANCE"},
    {"segment": "NSE_FO", "instrument_key": "NSE_FO|fut", "underlying_symbol": "RELIANCE",
     "instrument_type": "FUT", "lot_size": 250, "name": "RELIANCE"},
]


def test_from_upstox_json_keys_and_options():
    m = InstrumentMaster.from_upstox_json(DUMP)
    assert m.instrument_key_for("RELIANCE") == "NSE_EQ|INE002A01018"
    assert m.instrument_key_for("NIFTY 50") == "NSE_INDEX|Nifty 50"
    opts = m.option_keys_for("RELIANCE")
    assert len(opts) == 1 and opts[0]["option_type"] == "CE"
    assert len(m.option_keys_for("RELIANCE", expiry="2026-06-25")) == 1
    assert m.option_keys_for("RELIANCE", expiry="2099-01-01") == []
    assert m.lot_size("RELIANCE") == 250          # max lot across FO rows
    assert m.instrument_key_for("UNKNOWN") is None


def test_empty_master_falls_back_to_config():
    m = InstrumentMaster()
    assert m.instrument_key_for("NIFTY") is None
    assert m.lot_size("NIFTY") == 75              # config fallback


def test_load_cached_instruments_roundtrip(tmp_path):
    import json

    from anvil.ingest import instruments as inst

    p = tmp_path / "dump.json"
    p.write_text(json.dumps(DUMP), encoding="utf-8")
    try:
        m = inst.load_cached_instruments(str(p))
        assert m is not None and m.instrument_key_for("RELIANCE") == "NSE_EQ|INE002A01018"
        assert inst.get_master().instrument_key_for("RELIANCE") == "NSE_EQ|INE002A01018"
        assert inst.load_cached_instruments(str(tmp_path / "missing.json")) is None
    finally:
        inst.set_master(inst.InstrumentMaster())  # reset process-wide master


def test_cli_data_parser_has_new_actions():
    from anvil.cli import build_parser

    parser = build_parser()
    for action in ("fetch-candles", "fetch-instruments", "build-bars"):
        ns = parser.parse_args(["data", action, "--underlyings", "NIFTY", "--tf", "1m"])
        assert ns.action == action and ns.underlyings == "NIFTY" and ns.tf == "1m"
