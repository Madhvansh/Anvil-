"""M3: every analytics payload carries data provenance; demo is flagged demo, not live."""

from __future__ import annotations

from fastapi.testclient import TestClient

from anvil.api.app import app
from anvil.engine.provenance import data_mode
from anvil.ingest.capture import capture_rows
from anvil.ingest.demo import DemoConnector
from anvil.models import ChainRow, Greeks, OptionChain, OptionType
from anvil.pipeline import analyze_chain

client = TestClient(app)


def test_data_mode_mapping():
    assert data_mode("demo") == "demo"
    assert data_mode("seed") == "demo"
    assert data_mode("backtest") == "backtest"
    assert data_mode("upstox") == "live"
    assert data_mode(None) == "derived"


def test_pipeline_stamps_provenance():
    ch = DemoConnector().get_chain("NIFTY")
    p = analyze_chain(ch, source="demo")["provenance"]
    assert p["mode"] == "demo"
    assert p["source"] == "demo"
    assert p["engine_version"]
    assert p["forward_source"]  # forward is source-tagged
    # A bare engine call (no source) is honestly labeled "derived", never "live".
    assert analyze_chain(ch)["provenance"]["mode"] == "derived"


def test_api_analyze_exposes_provenance():
    j = client.get("/api/analyze/NIFTY").json()
    assert j["provenance"]["mode"] == "demo"
    assert j["provenance"]["underlying"] == "NIFTY"


def _chain_with_broker_greeks() -> OptionChain:
    # Brokers (e.g. Upstox) serve per-row greeks + iv; the demo chain does not.
    rows = []
    for k in (24000.0, 24100.0, 23900.0):
        for ot in (OptionType.CALL, OptionType.PUT):
            rows.append(
                ChainRow(
                    strike=k, option_type=ot, ltp=100.0, oi=1000.0, volume=10.0, iv=0.15,
                    greeks=Greeks(delta=0.5, gamma=0.0008, theta=-5.0, vega=8.0, rho=1.0),
                )
            )
    return OptionChain(
        underlying="NIFTY", spot=24000.0, expiry="2026-06-25",
        timestamp="2026-06-19T10:00:00+05:30", rows=rows,
        future_price=24010.0, future_price_source="provided", lot_size=75,
    )


def test_capture_rows_from_broker_greeks():
    rows = capture_rows(_chain_with_broker_greeks(), n=4)
    assert rows and len(rows) <= 4
    for key in ("option_type", "F", "strike", "T", "iv", "delta", "gamma", "theta_per_day", "vega_per_pct"):
        assert key in rows[0]


def test_capture_refuses_demo_only_chain():
    # Demo chain carries iv but no broker greeks → nothing to validate against (correctly empty).
    assert capture_rows(DemoConnector().get_chain("NIFTY")) == []
