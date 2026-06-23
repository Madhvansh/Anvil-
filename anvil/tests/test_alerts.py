"""M7: alert evaluation (grounded NL + severity) + rule CRUD + evaluate flow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anvil.api.app import app
from anvil.db import engine as dbengine
from anvil.engine.alerts import evaluate_rule, evaluate_rules

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'app.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def test_price_band_fires_with_nl_and_severity():
    payload = {"underlying": "NIFTY", "spot": 24000.0, "gex": {}, "oi": {}}
    rule = {"id": 1, "kind": "price_band", "underlying": "NIFTY", "params": {"lower": 24100, "upper": 24500}}
    ev = evaluate_rule(rule, payload)
    assert ev is not None
    assert ev["severity"] == "warn"
    assert "below" in ev["title"].lower()


def test_gex_flip_cross_needs_prior_and_fires_on_cross():
    cur = {"underlying": "NIFTY", "spot": 23900.0, "gex": {"zero_gamma_flip": 24000.0}, "oi": {}}
    prev = {"underlying": "NIFTY", "spot": 24100.0, "gex": {"zero_gamma_flip": 24000.0}, "oi": {}}
    assert evaluate_rule({"id": 1, "kind": "gex_flip_cross", "underlying": "NIFTY"}, cur) is None  # no prev
    ev = evaluate_rule({"id": 1, "kind": "gex_flip_cross", "underlying": "NIFTY"}, cur, prev=prev)
    assert ev is not None and ev["severity"] == "critical"
    assert "below the zero-gamma flip" in ev["title"]


def test_evaluate_rules_skips_disabled():
    payload = {"underlying": "NIFTY", "spot": 24000.0, "gex": {}, "oi": {}}
    rules = [{"id": 1, "kind": "price_band", "underlying": "NIFTY", "params": {"lower": 24100, "upper": 24500}, "enabled": False}]
    assert evaluate_rules(rules, payload) == []


def test_alert_crud_and_evaluate_endpoint(client):
    client.post("/auth/register", json=OWNER)
    assert client.get("/api/alerts").status_code == 200

    # A band guaranteed to trigger on the demo NIFTY spot.
    created = client.post("/api/alerts", json={"underlying": "NIFTY", "kind": "price_band", "params": {"lower": 99999, "upper": 100000}})
    assert created.status_code == 200
    rid = created.json()["id"]

    out = client.post("/api/alerts/evaluate/NIFTY").json()
    assert out["evaluated"] >= 1
    assert any(f["severity"] in ("info", "warn", "critical") and f["title"] for f in out["fired"])

    assert len(client.get("/api/alerts/events").json()) >= 1
    assert client.delete(f"/api/alerts/{rid}").status_code == 200


def test_alerts_gated(client):
    assert TestClient(app).get("/api/alerts").status_code == 401
