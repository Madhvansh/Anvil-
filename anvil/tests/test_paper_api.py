"""Phase 5 — gated paper API. Unauth -> 401; flag off -> 403; and the full authed loop:
generate recommendations, run a replay, read positions + equity curve. Demo source, no keys."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anvil.api import deps
from anvil.api.app import app
from anvil.db import engine as dbengine

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'paperapi.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def test_paper_endpoints_require_login():
    fresh = TestClient(app)
    assert fresh.get("/api/paper/account").status_code == 401
    assert fresh.get("/api/paper/recommendations/NIFTY").status_code == 401
    assert fresh.post("/api/paper/runs", json={}).status_code == 401


def test_paper_flag_off_returns_403(client, monkeypatch):
    client.post("/auth/register", json=OWNER)

    class _Off:
        paper_trading = False

    monkeypatch.setattr(deps, "SETTINGS", _Off())
    assert client.get("/api/paper/account").status_code == 403


def test_paper_full_loop(client):
    assert client.post("/auth/register", json=OWNER).status_code == 200

    acct = client.get("/api/paper/account")
    assert acct.status_code == 200 and acct.json()["account"]["starting_capital"] > 0

    recs = client.get("/api/paper/recommendations/NIFTY")
    assert recs.status_code == 200
    body = recs.json()
    assert body["underlying"] == "NIFTY" and isinstance(body["candidates"], list)
    assert "paper" in body["disclaimer"].lower()

    run = client.post("/api/paper/runs", json={"underlyings": ["NIFTY"], "steps": 3, "cadence_s": 14400,
                                               "seed": 7, "capital": 1_000_000,
                                               "start_ts": "2026-06-19T03:45:00+00:00", "expiry": "2026-06-26"})
    assert run.status_code == 200, run.text
    rep = run.json()
    assert "run_id" in rep and rep["summary"]["starting_capital"] == 1_000_000
    rid = rep["run_id"]

    curve = client.get(f"/api/paper/runs/{rid}/equity-curve")
    assert curve.status_code == 200 and len(curve.json()) >= 1

    positions = client.get("/api/paper/positions")
    assert positions.status_code == 200
    # The replay flattens at session end, so any persisted positions are closed.
    assert all(p["status"] == "closed" for p in positions.json())
