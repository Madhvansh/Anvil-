"""SQLite operational metadata: instruments, the snapshot registry, and ingest-run audit."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

_DEFAULT_INSTRUMENTS = [
    ("NIFTY", "Nifty 50", "NSE", 75, "index"),
    ("BANKNIFTY", "Nifty Bank", "NSE", 35, "index"),
]


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


class SqliteMeta:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: FastAPI runs sync endpoints across a threadpool.
        # timeout + busy_timeout + WAL keep concurrent writers from an immediate "database is locked".
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(_SCHEMA_PATH.read_text())
        self._conn.commit()

    def seed_instruments(self) -> None:
        self._conn.executemany(
            "INSERT OR IGNORE INTO instruments (symbol, name, exchange, lot_size, kind) "
            "VALUES (?, ?, ?, ?, ?)",
            _DEFAULT_INSTRUMENTS,
        )
        self._conn.commit()

    def register_snapshot(
        self,
        *,
        snapshot_id: str,
        underlying: str,
        expiry: str | None,
        snapshot_ts: str,
        source: str,
        chain_path: str,
        greeks_path: str | None,
        row_count: int,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO snapshots "
            "(snapshot_id, underlying, expiry, snapshot_ts, source, chain_path, greeks_path, "
            " row_count, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (snapshot_id, underlying, expiry, snapshot_ts, source, chain_path, greeks_path,
             row_count, _utcnow()),
        )
        self._conn.commit()

    def latest_snapshot_id(self, underlying: str) -> str | None:
        cur = self._conn.execute(
            "SELECT snapshot_id FROM snapshots WHERE underlying = ? "
            "ORDER BY snapshot_ts DESC, created_at DESC LIMIT 1",
            (underlying,),
        )
        row = cur.fetchone()
        return row["snapshot_id"] if row else None

    def get_snapshot(self, snapshot_id: str) -> dict | None:
        cur = self._conn.execute(
            "SELECT * FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def record_ingest_run(
        self,
        *,
        run_id: str,
        snapshot_id: str | None,
        source: str,
        status: str,
        started_at: str,
        finished_at: str | None = None,
        error: str | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ingest_runs "
            "(run_id, snapshot_id, source, status, started_at, finished_at, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, snapshot_id, source, status, started_at, finished_at, error),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
