"""M9: health reports version + DB connectivity; every response carries a request id."""

from __future__ import annotations

from fastapi.testclient import TestClient

from anvil.api.app import app

client = TestClient(app)


def test_health_reports_version_and_db():
    j = client.get("/health").json()
    assert j["status"] == "ok"
    assert j["version"]
    assert "db" in j  # bool — DB reachability


def test_request_id_header_present():
    r = client.get("/health")
    assert r.headers.get("x-request-id")
