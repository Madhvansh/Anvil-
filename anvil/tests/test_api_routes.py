"""M1 API-restructure smoke: the data endpoints live under /api/* and serve the demo
source end-to-end; the cockpit is still served at /. Old unprefixed paths are gone."""

from __future__ import annotations

from fastapi.testclient import TestClient

from anvil.api.app import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_cockpit_served_at_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_analyze_under_api():
    r = client.get("/api/analyze/NIFTY")
    assert r.status_code == 200
    j = r.json()
    assert j["underlying"] == "NIFTY"
    for key in ("gex", "implied_distribution", "regime", "oi"):
        assert key in j
    assert j["disclaimer"]


def test_gex_and_dist_slices():
    assert "total_gex" in client.get("/api/gex/NIFTY").json()
    assert "expected_move_1sigma" in client.get("/api/implied-dist/NIFTY").json()


def test_portfolio_risk_is_gated():
    # portfolio risk surfaces the user's positions → must require login (no cookie → 401).
    assert client.get("/api/portfolio-risk").status_code == 401


def test_old_unprefixed_paths_are_gone():
    assert client.get("/analyze/NIFTY").status_code == 404
    assert client.get("/gex/NIFTY").status_code == 404
