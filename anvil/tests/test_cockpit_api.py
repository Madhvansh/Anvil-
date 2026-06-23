"""Cockpit status API + build stamp + /health extension (Wave 0)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anvil.api.app import app
from anvil.api.buildinfo import build_stamp
from anvil.db import engine as dbengine

OWNER = {"email": "owner@anvil.test", "password": "supersecret1"}


@pytest.fixture
def client(tmp_path):
    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'cockpit.db').as_posix()}")
    with TestClient(app) as c:
        yield c


def test_build_stamp_shape():
    bs = build_stamp()
    assert set(bs) >= {"built", "index_mtime", "assets", "hash", "static_present"}
    assert isinstance(bs["assets"], int)


def test_cockpit_status_requires_login():
    assert TestClient(app).get("/api/cockpit/status").status_code == 401


def test_cockpit_status_payload(client):
    assert client.post("/auth/register", json=OWNER).status_code == 200
    r = client.get("/api/cockpit/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "build" in body and "supervisor" in body
    assert body["supervisor_running"] is False          # serve/test path: supervisor not started
    assert body["gate0_passed"] is False                # no certified cell
    assert body["personal_mode_armed"] is False
    assert isinstance(body["cockpit_underlyings"], list)


def test_health_has_build_and_supervisor(client):
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "build" in body and body["supervisor_running"] is False
