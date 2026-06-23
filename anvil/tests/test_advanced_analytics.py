"""M8: high-value analytics — scenario grid, Monte Carlo, event/expiry risk, IV-crush,
unusual activity, participant-OI. Exercised on the demo source (chain + positions)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from anvil.api.app import app
from anvil.engine.event_risk import event_risk
from anvil.engine.iv_crush import iv_crush_warning
from anvil.engine.montecarlo import mc_pnl
from anvil.engine.participant_oi import participant_oi_read
from anvil.engine.scenarios import scenario_grid
from anvil.engine.unusual import unusual_activity
from anvil.ingest.nse_eod import ParticipantOI
from anvil.ingest.demo import DemoConnector

client = TestClient(app)


def _chain_and_positions():
    conn = DemoConnector()
    return conn.get_chain("NIFTY"), conn.get_positions()


def test_scenario_grid_pnl_signs():
    ch, pos = _chain_and_positions()
    grid = scenario_grid(ch, pos)
    assert grid["has_positions"] is True
    # Flat scenario (0,0) is ~zero P&L (model value vs itself).
    flat = next(c for c in grid["cells"] if c["spot_shock"] == 0.0 and c["vol_shift"] == 0.0)
    assert abs(flat["pnl"]) < 1.0
    # The demo book is a short straddle: a big move in either direction should hurt it somewhere.
    assert grid["worst"]["pnl"] < 0


def test_monte_carlo_pnl_sane():
    ch, pos = _chain_and_positions()
    mc = mc_pnl(ch, pos, horizon_days=5.0, n_paths=4000, seed=7)
    assert mc["available"] is True
    assert 0.0 <= mc["p_profit"] <= 1.0
    assert mc["percentiles"]["p5"] <= mc["percentiles"]["p50"] <= mc["percentiles"]["p95"]
    assert mc["var_95"] == mc["var_95"]  # not NaN
    assert sum(mc["histogram"]["counts"]) == 4000


def test_event_and_iv_crush_and_unusual():
    ch, _ = _chain_and_positions()
    ev = event_risk(ch)
    assert ev["risk_level"] in ("low", "medium", "high")
    assert ev["days_to_expiry"] >= 0

    crush = iv_crush_warning(ch, history_iv=[0.10, 0.12, 0.14, 0.16, 0.18])
    assert 0 <= crush["crush_score"] <= 100
    assert crush["level"] in ("low", "medium", "high")

    ua = unusual_activity(ch)
    assert "flags" in ua and "total_oi_change" in ua


def test_participant_oi_parsing_injected():
    data = ParticipantOI(
        date="19062026",
        rows=[
            {
                "Client Type": "FII",
                "Future Index Long": "1,000",
                "Future Index Short": "400",
                "Option Index Call Long": "800",
                "Option Index Put Long": "300",
            }
        ],
    )
    out = participant_oi_read(data=data, vix=13.5)
    assert out["available"] is True
    assert out["participants"]["FII"]["future_index_net"] == 600.0
    assert "FII" in out["narrative"]


def test_public_advanced_endpoints():
    # Market analytics are public within the instance.
    assert client.get("/api/event-risk/NIFTY").json()["risk_level"] in ("low", "medium", "high")
    assert "crush_score" in client.get("/api/iv-crush/NIFTY").json()
    assert "flags" in client.get("/api/unusual/NIFTY").json()
    # participant-OI degrades gracefully without a date / network.
    assert "available" in client.get("/api/participant-oi/NIFTY").json()


def test_position_bearing_endpoints_are_gated():
    # scenario + Monte Carlo reprice the user's book → require login.
    assert client.get("/api/scenario/NIFTY").status_code == 401
    assert client.post("/api/montecarlo/NIFTY", json={"n_paths": 100}).status_code == 401
