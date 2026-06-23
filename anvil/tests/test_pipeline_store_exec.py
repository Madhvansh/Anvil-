"""End-to-end pipeline, snapshot store, and the gated execution layer."""

import pytest

from anvil.execution import (
    AssistedExecutor,
    AutoExecutor,
    OrderRequest,
    TradingDisabledError,
)
from anvil.ingest.demo import DemoConnector
from anvil.pipeline import analyze_chain, to_snapshot
from anvil.store import SnapshotStore


def test_pipeline_full_payload():
    conn = DemoConnector()
    chain = conn.get_chain("NIFTY")
    payload = analyze_chain(chain, conn.get_positions())
    for key in ("oi", "gex", "implied_distribution", "regime", "portfolio", "skew"):
        assert key in payload
    assert payload["gex"]["zero_gamma_flip"] is not None
    assert payload["regime"]["label"]
    assert payload["portfolio"]["benchmark"] == "NIFTY"


def test_to_snapshot_and_store(tmp_path):
    conn = DemoConnector()
    payload = analyze_chain(conn.get_chain("NIFTY"), conn.get_positions())
    snap = to_snapshot(payload)
    store = SnapshotStore(path=str(tmp_path / "t.duckdb"))
    store.write(snap, payload)
    assert store.count("NIFTY") == 1
    rows = store.latest("NIFTY")
    assert rows and rows[0][1] == snap.spot
    store.close()


def test_auto_executor_gated_off_by_default():
    ex = AutoExecutor()
    with pytest.raises(TradingDisabledError):
        ex.place(OrderRequest(symbol="NIFTY24000CE", side="SELL", quantity=75))


def test_assisted_executor_requires_confirmation():
    ex = AssistedExecutor()
    ticket = ex.propose(OrderRequest(symbol="NIFTY24000CE", side="SELL", quantity=75))
    assert ticket.status == "PENDING_USER_CONFIRMATION"
    # no gateway configured => confirmation is blocked, never silently placed
    confirmed = ex.confirm(ticket)
    assert confirmed.status == "BLOCKED"
