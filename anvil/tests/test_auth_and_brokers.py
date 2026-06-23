"""M4: token store expiry, Kite checksum, Upstox parse/URL, gated Groww gateway, Groww parse.

All offline — broker SDKs are faked, no network or credentials required."""

import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from anvil.auth import kite_auth, upstox_auth
from anvil.auth.token_store import TokenStore, expiry_at_0330_ist

IST = timezone(timedelta(hours=5, minutes=30))


# ---- token store ----
def test_expiry_rolls_to_next_0330():
    before = datetime(2026, 6, 18, 2, 0, tzinfo=IST)  # 02:00 IST → same-day 03:30
    assert expiry_at_0330_ist(before).hour == 3 and expiry_at_0330_ist(before).day == 18
    after = datetime(2026, 6, 18, 9, 0, tzinfo=IST)  # 09:00 IST → next-day 03:30
    assert expiry_at_0330_ist(after).day == 19


def test_token_store_roundtrip_and_validity(tmp_path):
    s = TokenStore(directory=str(tmp_path))
    s.save("upstox", "tok123", expires_at=datetime.now(IST) + timedelta(hours=1))
    assert s.is_valid("upstox")
    assert s.access_token("upstox") == "tok123"
    s.save("kite", "old", expires_at=datetime.now(IST) - timedelta(hours=1))  # already expired
    assert not s.is_valid("kite")
    assert s.access_token("kite") is None
    assert s.load("groww") is None


# ---- kite checksum ----
def test_kite_checksum_known_vector():
    expected = hashlib.sha256(b"apikeyreqtokensecret").hexdigest()
    assert kite_auth.checksum("apikey", "reqtoken", "secret") == expected


def test_kite_login_url():
    assert "api_key=ABC" in kite_auth.login_url("ABC")


# ---- upstox ----
def test_upstox_dialog_url():
    url = upstox_auth.build_dialog_url("cid", "http://127.0.0.1:8765/callback", "anvil")
    assert "response_type=code" in url and "client_id=cid" in url and "state=anvil" in url


def test_upstox_parse_chain():
    from anvil.ingest.upstox import UpstoxConnector

    conn = UpstoxConnector("dummy-token")
    payload = [
        {
            "strike_price": 24000,
            "underlying_spot_price": 24010,
            "call_options": {
                "market_data": {"ltp": 120, "oi": 1000, "prev_oi": 900, "volume": 50, "bid_price": 119, "ask_price": 121},
                "option_greeks": {"delta": 0.5, "gamma": 0.0002, "theta": -5, "vega": 8, "iv": 13.5},
            },
            "put_options": {
                "market_data": {"ltp": 110, "oi": 1200, "prev_oi": 1300, "volume": 60},
                "option_greeks": {"delta": -0.5, "gamma": 0.0002, "theta": -4, "vega": 8, "iv": 14.0},
            },
        }
    ]
    chain = conn._parse_chain("NIFTY", "2026-07-31", payload)
    conn.close()
    assert chain.spot == 24010
    assert len(chain.rows) == 2
    assert any(r.oi == 1000 and r.oi_change == 100 for r in chain.rows)  # 1000 - 900
    assert any(r.iv == pytest.approx(0.135) for r in chain.rows)  # 13.5% -> decimal


# ---- gated Groww order gateway ----
class _FakeGroww:
    EXCHANGE_NSE = "NSE"
    SEGMENT_FNO = "FNO"
    PRODUCT_NRML = "NRML"
    ORDER_TYPE_LIMIT = "LIMIT"
    VALIDITY_DAY = "DAY"
    TRANSACTION_TYPE_BUY = "BUY"
    TRANSACTION_TYPE_SELL = "SELL"

    def __init__(self):
        self.calls = []

    def place_order(self, **kw):
        self.calls.append(kw)
        return {"groww_order_id": "GW123", "order_status": "OPEN"}


def _req():
    from anvil.execution.gateway import OrderRequest

    return OrderRequest(symbol="NIFTY24000CE", side="SELL", quantity=75, order_type="LIMIT", price=120.0)


def test_groww_gateway_dry_run_never_calls_broker():
    from anvil.execution.groww_gateway import GrowwOrderGateway

    fake = _FakeGroww()
    gw = GrowwOrderGateway(client=fake, dry_run=True)
    ticket = gw.place(_req())
    assert ticket.status == "SIMULATED"
    assert fake.calls == []  # broker never touched


def test_groww_gateway_live_places_once():
    from anvil.execution.groww_gateway import GrowwOrderGateway

    fake = _FakeGroww()
    gw = GrowwOrderGateway(client=fake, dry_run=False)
    ticket = gw.place(_req())
    assert ticket.status == "PLACED"
    assert ticket.broker_order_id == "GW123"
    assert len(fake.calls) == 1
    assert fake.calls[0]["transaction_type"] == "SELL"
    assert fake.calls[0]["segment"] == "FNO"


def test_assisted_executor_with_groww_dry_run():
    from anvil.execution.gateway import AssistedExecutor
    from anvil.execution.groww_gateway import GrowwOrderGateway

    fake = _FakeGroww()
    ex = AssistedExecutor(gateway=GrowwOrderGateway(client=fake, dry_run=True))
    ticket = ex.propose(_req())
    assert ticket.status == "PENDING_USER_CONFIRMATION"
    placed = ex.confirm(ticket)
    assert placed.status == "SIMULATED"
    assert fake.calls == []


# ---- Groww connector parse ----
class _FakeGrowwData:
    EXCHANGE_NSE = "NSE"

    def get_option_chain(self, exchange, underlying, expiry_date):
        return {
            "underlying_ltp": 24000,
            "option_chain": [
                {
                    "strike_price": 24000,
                    "call": {"ltp": 120, "open_interest": 1000, "iv": 13.5, "delta": 0.5, "gamma": 0.0002, "theta": -5, "vega": 8},
                    "put": {"ltp": 110, "open_interest": 1200, "iv": 14.0},
                }
            ],
        }


def test_groww_connector_parse():
    from anvil.ingest.groww import GrowwConnector

    conn = GrowwConnector(client=_FakeGrowwData())
    chain = conn.get_chain("NIFTY", "2026-07-31")
    assert chain.spot == 24000
    assert len(chain.rows) == 2
    call = [r for r in chain.rows if r.option_type.value == "CE"][0]
    assert call.oi == 1000 and call.greeks is not None and call.iv == pytest.approx(0.135)
