"""API: /analytics/{underlying} and /calibration — shape, honesty flags, disclaimer, errors."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

pytestmark = [pytest.mark.unit]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from oip.config import get_settings

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


def test_analytics_payload_shape_and_honesty_flags(client):
    j = client.get("/analytics/NIFTY").json()
    assert j["underlying"] == "NIFTY"
    assert j["future_price_source"] == "nse_futures"
    assert "pcr_oi" in j["oi"] and "max_pain" in j["oi"]
    assert "atm_iv" in j["vol"] and isinstance(j["vol"]["smile"], list)
    assert j["gex"]["needs_nse_validation"] is True            # honesty flag
    assert j["implied_distribution"]["needs_real_world_calibration"] is True  # honesty flag
    assert j["implied_distribution"]["em_atm_iv"] is not None
    assert j["disclaimer"]


def test_analytics_lowercase_canonicalized_and_unknown_404(client):
    assert client.get("/analytics/nifty").status_code == 200
    assert client.get("/analytics/DOESNOTEXIST").status_code == 404


def test_calibration_empty_summary(client):
    j = client.get("/calibration?underlying=NIFTY").json()
    assert j["n_forecasts"] == 0
    assert j["n_resolved"] == 0
    assert j["brier"] is None
    assert len(j["reliability"]) == 10
    assert j["disclaimer"]
