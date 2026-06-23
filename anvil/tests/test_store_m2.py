"""M2: deterministic idempotent snapshots, cleaned chain time-series, audit, Parquet export."""

import os

from anvil.ingest.demo import DemoConnector
from anvil.pipeline import analyze_chain, to_snapshot
from anvil.store.timeseries import SnapshotStore, snapshot_id_for


def test_snapshot_id_is_deterministic():
    a = snapshot_id_for("NIFTY", "2026-07-31", "2026-06-18T06:00:00+00:00", "demo")
    b = snapshot_id_for("NIFTY", "2026-07-31", "2026-06-18T06:00:00+00:00", "demo")
    assert a == b
    assert a != snapshot_id_for("NIFTY", "2026-07-31", "2026-06-18T06:00:01+00:00", "demo")


def _chain_payload():
    conn = DemoConnector()
    chain = conn.get_chain("NIFTY")
    payload = analyze_chain(chain, conn.get_positions())
    return chain, payload


def test_write_is_idempotent(tmp_path):
    chain, payload = _chain_payload()
    store = SnapshotStore(path=str(tmp_path / "s.duckdb"))
    snap = to_snapshot(payload)
    store.write(snap, payload, source="demo", chain=chain)
    store.write(snap, payload, source="demo", chain=chain)  # same data again → no dup
    assert store.count("NIFTY") == 1
    n_rows = store.con.execute("SELECT count(*) FROM chain_rows").fetchone()[0]
    assert n_rows == len(chain.rows)  # not doubled
    store.close()


def test_chain_rows_persisted(tmp_path):
    chain, payload = _chain_payload()
    store = SnapshotStore(path=str(tmp_path / "s.duckdb"))
    store.write(to_snapshot(payload), payload, source="demo", chain=chain)
    n_rows = store.con.execute("SELECT count(*) FROM chain_rows").fetchone()[0]
    assert n_rows == len(chain.rows)
    # cleaned time-series carries OI + IV per leg
    sample = store.con.execute("SELECT oi, iv FROM chain_rows WHERE iv IS NOT NULL LIMIT 1").fetchone()
    assert sample is not None and sample[0] is not None
    store.close()


def test_audit_log_records_ok_then_duplicate(tmp_path):
    chain, payload = _chain_payload()
    store = SnapshotStore(path=str(tmp_path / "s.duckdb"))
    snap = to_snapshot(payload)
    store.write(snap, payload, source="demo", chain=chain)
    store.write(snap, payload, source="demo", chain=chain)
    statuses = [r[3] for r in store.audit_log()]
    assert "ok" in statuses and "duplicate" in statuses
    store.close()


def test_export_parquet(tmp_path):
    chain, payload = _chain_payload()
    store = SnapshotStore(path=str(tmp_path / "s.duckdb"))
    store.write(to_snapshot(payload), payload, source="demo", chain=chain)
    out = store.export_parquet(str(tmp_path / "parquet"))
    store.close()
    # partitioned by underlying → at least one parquet file under underlying=NIFTY
    found = []
    for root, _dirs, files in os.walk(out):
        found += [f for f in files if f.endswith(".parquet")]
    assert found
