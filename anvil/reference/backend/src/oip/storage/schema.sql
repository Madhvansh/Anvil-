-- SQLite operational metadata for Phase 0 (ADR 0003).
-- Kept intentionally small so the Phase 1 migration to Postgres/Timescale is easy.

CREATE TABLE IF NOT EXISTS instruments (
    symbol    TEXT PRIMARY KEY,
    name      TEXT,
    exchange  TEXT,
    lot_size  INTEGER,
    kind      TEXT
);

-- Registry pointing at the columnar snapshots in the Parquet lake.
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id TEXT PRIMARY KEY,
    underlying  TEXT NOT NULL,
    expiry      TEXT,
    snapshot_ts TEXT NOT NULL,
    source      TEXT NOT NULL,
    chain_path  TEXT NOT NULL,
    greeks_path TEXT,
    row_count   INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snapshots_underlying ON snapshots (underlying, snapshot_ts);

-- Audit trail for ingest pipeline runs.
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id      TEXT PRIMARY KEY,
    snapshot_id TEXT,
    source      TEXT,
    status      TEXT,
    started_at  TEXT,
    finished_at TEXT,
    error       TEXT
);
