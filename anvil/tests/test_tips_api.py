"""Gated tips API: unauth -> 401; flag off -> 403; and the authed reads — live tips split into a
disjoint headline/watchlist (headline empty without measured evidence), track-record curves, feed."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import anvil.api.routers.tips as tipsmod
from anvil.api import deps
from anvil.api.app import app
from anvil.db import engine as dbengine
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.store import IssuedTipStore, TipValidationStore

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'tipsapi.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def _isolate_stores(monkeypatch, tmp_path):
    """Point the router's ledger/stores at tmp DuckDB files (never the user's real moat)."""
    monkeypatch.setattr(tipsmod, "TipValidationStore", lambda path=None: TipValidationStore(str(tmp_path / "tv.duckdb")))
    monkeypatch.setattr(tipsmod, "IssuedTipStore", lambda path=None: IssuedTipStore(str(tmp_path / "iss.duckdb")))
    monkeypatch.setattr(tipsmod, "CalibrationLedger", lambda path=None: CalibrationLedger(str(tmp_path / "l.duckdb")))


def test_tips_endpoints_require_login():
    fresh = TestClient(app)
    assert fresh.get("/api/tips/NIFTY").status_code == 401
    assert fresh.get("/api/tips/track-record").status_code == 401
    assert fresh.get("/api/tips/feed").status_code == 401


def test_tips_flag_off_returns_403(client, monkeypatch):
    client.post("/auth/register", json=OWNER)

    class _Off:
        tips_enabled = False

    monkeypatch.setattr(deps, "SETTINGS", _Off())
    assert client.get("/api/tips/NIFTY").status_code == 403


def test_live_tips_split_headline_and_watchlist(client, monkeypatch, tmp_path):
    assert client.post("/auth/register", json=OWNER).status_code == 200
    _isolate_stores(monkeypatch, tmp_path)

    r = client.get("/api/tips/NIFTY")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["underlying"] == "NIFTY"
    assert "disclaimer" in body and body["disclaimer"]
    assert isinstance(body["headline"], list) and isinstance(body["watchlist"], list)
    # the never-empty live read is ALWAYS present, even with an empty headline feed
    pred = body["prediction"]
    assert pred["underlying"] == "NIFTY"
    assert pred["direction"] and 0.0 <= pred["confidence"] <= 1.0
    assert pred["edge_verified"] is False  # no measured evidence yet
    assert "tip_calibration" in body
    # no validation evidence yet → headline is empty by design (the honest default)
    assert body["headline"] == []
    # headline and watchlist never share a tip
    h_ids = {t["tip_id"] for t in body["headline"]}
    w_ids = {t["tip_id"] for t in body["watchlist"]}
    assert h_ids.isdisjoint(w_ids)
    # every surfaced tip carries its tier + disclaimer + cost-adjusted EV
    for t in body["headline"] + body["watchlist"]:
        assert t["tier"] in ("headline", "watchlist")
        assert "cost_adjusted_ev" in t


def test_track_record_returns_both_tip_curves(client, monkeypatch, tmp_path):
    client.post("/auth/register", json=OWNER)
    _isolate_stores(monkeypatch, tmp_path)

    r = client.get("/api/tips/track-record")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["by_class"]) == {"tip_backtest", "tip_live"}
    assert isinstance(body["cells"], list)
    assert body["disclaimer"]


def test_feed_returns_list(client, monkeypatch, tmp_path):
    client.post("/auth/register", json=OWNER)
    _isolate_stores(monkeypatch, tmp_path)

    r = client.get("/api/tips/feed", params={"limit": 10})
    assert r.status_code == 200, r.text
    assert isinstance(r.json()["tips"], list)
