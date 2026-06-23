"""API routes: shape, the mandatory disclaimer, error codes, and the static page."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from oip.config import get_settings

    # Locate the committed fixture via current settings, then isolate the data dir to tmp.
    get_settings.cache_clear()
    src_fixture = get_settings().fixtures_dir / "nse_chain_NIFTY_2026-06-12.json"

    monkeypatch.setenv("OIP_DATA_DIR", str(tmp_path))
    get_settings.cache_clear()
    settings = get_settings()
    settings.fixtures_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(src_fixture, settings.fixtures_dir / src_fixture.name)

    from oip.api.app import create_app

    with TestClient(create_app()) as c:
        yield c
    get_settings.cache_clear()


def test_health(client):
    j = client.get("/health").json()
    assert j["status"] == "ok"
    assert j["engine_version"]
    assert "not investment advice" in j["disclaimer"]


def test_chain_shape_and_disclaimer(client):
    r = client.get("/chain?underlying=NIFTY")
    assert r.status_code == 200
    j = r.json()
    assert j["underlying"] == "NIFTY"
    assert j["future_price"] == pytest.approx(22014.5)
    assert j["future_price_source"] == "nse_futures"
    assert j["disclaimer"]
    assert len(j["rows"]) == 5
    row = next(x for x in j["rows"] if x["strike"] == 22000.0)
    assert row["call"]["delta"] is not None
    assert row["put"]["delta"] is not None
    assert row["call"]["iv_used"] == pytest.approx(0.124)


def test_chain_by_id_roundtrip(client):
    sid = client.get("/chain?underlying=NIFTY").json()["snapshot_id"]
    r = client.get(f"/chain/{sid}")
    assert r.status_code == 200
    assert r.json()["snapshot_id"] == sid


def test_chain_unknown_snapshot_404(client):
    assert client.get("/chain/NOPE").status_code == 404


def test_greeks_single_leg(client):
    j = client.get("/greeks?underlying=NIFTY&strike=22000&option_type=c").json()
    assert j["strike"] == 22000.0
    assert j["option_type"] == "c"
    assert j["delta"] is not None
    assert j["price_model"] == "black76"
    assert j["disclaimer"]


def test_greeks_bad_option_type_400(client):
    assert client.get("/greeks?underlying=NIFTY&strike=22000&option_type=zzz").status_code == 400


def test_greeks_missing_strike_404(client):
    assert client.get("/greeks?underlying=NIFTY&strike=99999&option_type=c").status_code == 404


def test_static_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Black-76" in r.text
    assert "not investment advice" in r.text


def test_static_banner_carries_full_canonical_disclaimer(client):
    from oip.constants import DISCLAIMER

    # The persistent banner must show the full canonical text even before JS runs.
    assert DISCLAIMER in client.get("/").text
