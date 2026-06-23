"""Momentum API: unauth → 401; authed read returns the momentum/flow/prediction payload (network-free)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import anvil.api.routers.momentum as mommod
from anvil.api.app import app
from anvil.db import engine as dbengine
from anvil.store.bars import BarStore
from anvil.store.timeseries import SnapshotStore
from anvil.tips import series as seriesmod
from anvil.tips.store import TipValidationStore

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'momapi.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def _isolate(monkeypatch, tmp_path):
    """Point stores at tmp DuckDB + stub Yahoo so the test never touches the real moat or the network."""
    monkeypatch.setattr(mommod, "BarStore", lambda path=None: BarStore(str(tmp_path / "bars.duckdb")))
    monkeypatch.setattr(mommod, "SnapshotStore", lambda path=None: SnapshotStore(str(tmp_path / "snap.duckdb")))
    monkeypatch.setattr(mommod, "TipValidationStore", lambda path=None: TipValidationStore(str(tmp_path / "tv.duckdb")))
    monkeypatch.setattr(seriesmod.yahoo, "read_cache", lambda sym: [])


def test_momentum_requires_login():
    assert TestClient(app).get("/api/momentum/NIFTY").status_code == 401


def test_momentum_endpoint_returns_payload(client, monkeypatch, tmp_path):
    assert client.post("/auth/register", json=OWNER).status_code == 200
    _isolate(monkeypatch, tmp_path)

    r = client.get("/api/momentum/NIFTY")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["underlying"] == "NIFTY"
    assert "momentum" in body and "flow" in body and "momentum_factors" in body
    assert body["prediction"]["underlying"] == "NIFTY"
    assert body["disclaimer"]
