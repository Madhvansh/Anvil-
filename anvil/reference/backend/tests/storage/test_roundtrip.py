"""Storage round-trip + reproducibility: written Greeks read back bit-for-bit."""

from __future__ import annotations

import pytest

from oip.quant.greeks_service import compute_chain_greeks
from oip.storage.duck import DuckStore

pytestmark = [pytest.mark.unit]

_SID = "NIFTY_20260626_20260612T153000_test"


def test_chain_roundtrip(tmp_path, sample_chain):
    store = DuckStore(tmp_path / "snapshots")
    store.write_snapshot(_SID, sample_chain)
    rows = store.read_chain(_SID)
    assert len(rows) == 6  # 3 strikes x (call + put)
    leg = next(r for r in rows if r["strike"] == 22000.0 and r["option_type"] == "c")
    assert leg["iv_source"] == pytest.approx(0.124)
    assert leg["future_price"] == pytest.approx(22014.5)
    assert leg["future_price_source"] == "nse_futures"
    assert leg["oi"] == 100000


def test_greeks_roundtrip_is_reproducible(tmp_path, sample_chain):
    store = DuckStore(tmp_path / "snapshots")
    greeks = compute_chain_greeks(sample_chain)
    store.write_snapshot(_SID, sample_chain)
    store.write_greeks(_SID, sample_chain, greeks)

    joined = store.read_chain_with_greeks(_SID)
    assert len(joined) == 6
    by_key = {(g.strike, g.option_type.value): g for g in greeks}
    for row in joined:
        g = by_key[(row["strike"], row["option_type"])]
        assert row["delta"] == pytest.approx(g.delta, rel=1e-12, abs=1e-12)
        assert row["gamma"] == pytest.approx(g.gamma, rel=1e-12, abs=1e-12)
        assert row["theta_per_day"] == pytest.approx(g.theta_per_day, rel=1e-12, abs=1e-12)
        assert row["vega_per_pct"] == pytest.approx(g.vega_per_pct, rel=1e-12, abs=1e-12)
        assert row["price"] == pytest.approx(g.price, rel=1e-12, abs=1e-12)
        assert row["engine_version"] == g.engine_version


def test_read_missing_snapshot_returns_empty(tmp_path):
    store = DuckStore(tmp_path / "snapshots")
    assert store.read_chain("nope") == []
    assert store.read_chain_with_greeks("nope") == []


def _chain(rows, snap_minute=30):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from oip.domain.enums import Exchange, FuturePriceSource
    from oip.domain.models import OptionChain

    return OptionChain(
        underlying="NIFTY", exchange=Exchange.NSE, spot=21990.0, future_price=22010.0,
        future_price_source=FuturePriceSource.NSE_FUTURES,
        snapshot_ts=datetime(2026, 6, 12, 15, snap_minute, tzinfo=ZoneInfo("Asia/Kolkata")),
        risk_free_rate=0.065, rows=rows,
    )


def test_multi_expiry_join_pairs_each_legs_own_expiry(tmp_path):
    from datetime import date

    from oip.domain.enums import OptionType
    from oip.domain.models import ChainRow, OptionQuote
    from oip.quant.greeks_service import year_fraction

    def q(ot, iv):
        return OptionQuote(option_type=ot, last_price=100.0, iv_source=iv)

    rows = [
        ChainRow(strike=22000.0, expiry=date(2026, 6, 26),
                 call=q(OptionType.CALL, 0.12), put=q(OptionType.PUT, 0.13)),
        ChainRow(strike=22000.0, expiry=date(2026, 7, 31),
                 call=q(OptionType.CALL, 0.14), put=q(OptionType.PUT, 0.15)),
    ]
    chain = _chain(rows)
    store = DuckStore(tmp_path / "snapshots")
    greeks = compute_chain_greeks(chain)
    store.write_snapshot("sid", chain)
    store.write_greeks("sid", chain, greeks)

    joined = store.read_chain_with_greeks("sid")
    assert len(joined) == 4  # 2 expiries x (call+put); would be 8 (cross-product) without expiry key
    for row in joined:
        exp = date.fromisoformat(row["expiry"])
        assert row["t_years"] == pytest.approx(year_fraction(chain.snapshot_ts, exp), rel=1e-9)


def test_read_chain_output_is_json_serializable(tmp_path, sample_chain):
    import json

    store = DuckStore(tmp_path / "snapshots")
    store.write_snapshot("sid", sample_chain)
    rows = store.read_chain("sid")
    json.dumps(rows)  # must not raise — no pandas.Timestamp / NaT leaking through
    assert "snapshot_date" not in rows[0]  # hive partition column is not injected


def test_oi_volume_stay_int_when_a_null_is_present(tmp_path):
    from datetime import date

    from oip.domain.enums import OptionType
    from oip.domain.models import ChainRow, OptionQuote

    rows = [
        ChainRow(
            strike=22000.0, expiry=date(2026, 6, 26),
            call=OptionQuote(option_type=OptionType.CALL, last_price=100.0, oi=12345, volume=678, iv_source=0.12),
            put=OptionQuote(option_type=OptionType.PUT, last_price=90.0, oi=None, volume=None, iv_source=0.13),
        ),
    ]
    store = DuckStore(tmp_path / "snapshots")
    store.write_snapshot("sid", _chain(rows))
    recs = store.read_chain("sid")
    call = next(r for r in recs if r["option_type"] == "c")
    put = next(r for r in recs if r["option_type"] == "p")
    assert call["oi"] == 12345 and isinstance(call["oi"], int)
    assert isinstance(call["volume"], int)
    assert put["oi"] is None and put["volume"] is None
