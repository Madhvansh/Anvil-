"""M6: daily brief, what-changed, human calibration, mode-aware copilot, daily cycle."""

from __future__ import annotations

from fastapi.testclient import TestClient

from anvil.api.app import app
from anvil.engine.brief import daily_brief
from anvil.engine.whatchanged import what_changed
from anvil.ingest.demo import DemoConnector
from anvil.ledger.ledger import CalibrationLedger
from anvil.live.cycle import run_daily_cycle
from anvil.pipeline import analyze_chain
from anvil.store import SnapshotStore

client = TestClient(app)


def test_what_changed_diff():
    ch = DemoConnector().get_chain("NIFTY")
    today = analyze_chain(ch, source="demo")
    assert what_changed(today, None)["available"] is False  # no baseline
    # Synthesize a baseline with a lower spot/IV → expect up moves + a narrative.
    base = analyze_chain(ch, source="demo")
    base["spot"] = today["spot"] - 100
    if base.get("implied_distribution"):
        base["implied_distribution"]["atm_iv"] = (today["implied_distribution"]["atm_iv"] or 0.1) - 0.02
    wc = what_changed(today, base)
    assert wc["available"] is True
    assert any(c["field"] == "spot" for c in wc["changes"])
    assert wc["narrative"]


def test_daily_brief_lines():
    ch = DemoConnector().get_chain("NIFTY")
    brief = daily_brief(analyze_chain(ch, source="demo"))
    assert brief["lines"] and len(brief["lines"]) >= 3
    assert brief["underlying"] == "NIFTY"


def test_run_daily_cycle_idempotent(tmp_path):
    store = SnapshotStore(path=str(tmp_path / "s.duckdb"))
    ledger = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    conn = DemoConnector()
    # record_tips=False: this test isolates the forecast/snapshot idempotency; the tip pass opens
    # its own (real-path) stores and is covered by the tips suites.
    r1 = run_daily_cycle(["NIFTY"], connector=conn, store=store, ledger=ledger, record_tips=False)
    n1 = store.count("NIFTY")
    p1 = len(ledger.pending("NIFTY"))
    run_daily_cycle(["NIFTY"], connector=conn, store=store, ledger=ledger, record_tips=False)
    n2 = store.count("NIFTY")
    p2 = len(ledger.pending("NIFTY"))
    store.close()
    ledger.close()
    assert r1["snapshots"]["NIFTY"]
    assert n1 == n2  # same snapshot id → no duplicate snapshot
    assert p1 == p2 and p1 > 0  # content-hashed forecast ids → ledger doesn't inflate on re-run


def test_endpoints():
    assert client.get("/api/daily-brief/NIFTY").json()["lines"]
    assert "available" in client.get("/api/what-changed/NIFTY").json()
    assert "by_class" in client.get("/api/calibration").json()
    nar = client.get("/api/copilot/narrate/NIFTY", params={"mode": "simple"}).json()
    assert nar["mode"] == "simple" and nar["answer"]
    ask = client.post("/api/copilot/ask/NIFTY", json={"question": "explain today simply"}).json()
    assert ask["answer"] and ask["grounded"] is True
