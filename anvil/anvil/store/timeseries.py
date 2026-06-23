"""DuckDB-backed snapshot store — the proprietary, reproducible data moat.

Three tables, all keyed for **idempotency** so re-ingesting the same data never duplicates or
silently rewrites history:
  * ``snapshots``  — one computed analytics summary per (underlying, expiry, timestamp, source)
  * ``chain_rows`` — the cleaned per-strike OI/IV/greeks time-series (what compounds over time)
  * ``ingest_runs``— an append-only audit of every write (success / duplicate / error)

DuckDB is embedded (single file, no server) and can export the moat dataset to partitioned
Parquet on demand (:meth:`export_parquet`). Migrate the same schema to TimescaleDB at scale.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import duckdb

from ..config import SETTINGS
from ..models import OptionChain, Snapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id VARCHAR PRIMARY KEY,
    underlying VARCHAR, ts VARCHAR, expiry VARCHAR, source VARCHAR, spot DOUBLE,
    pcr_oi DOUBLE, pcr_volume DOUBLE, max_pain DOUBLE, total_gex DOUBLE,
    zero_gamma_flip DOUBLE, expected_move_1s DOUBLE, atm_iv DOUBLE, regime VARCHAR, payload JSON
);
CREATE TABLE IF NOT EXISTS chain_rows (
    snapshot_id VARCHAR, underlying VARCHAR, ts VARCHAR, expiry VARCHAR,
    strike DOUBLE, option_type VARCHAR, ltp DOUBLE, oi DOUBLE, oi_change DOUBLE,
    volume DOUBLE, iv DOUBLE,
    PRIMARY KEY (snapshot_id, strike, option_type)
);
CREATE SEQUENCE IF NOT EXISTS ingest_run_seq START 1;
CREATE TABLE IF NOT EXISTS ingest_runs (
    run_id INTEGER DEFAULT nextval('ingest_run_seq'),
    snapshot_id VARCHAR, underlying VARCHAR, recorded_at VARCHAR,
    status VARCHAR, rows INTEGER, error VARCHAR
);
"""


def snapshot_id_for(underlying: str, expiry: str, timestamp: str, source: str = "anvil") -> str:
    """Deterministic id → re-ingesting identical data is a no-op (idempotent)."""
    return f"{underlying}|{expiry}|{timestamp}|{source}"


class SnapshotStore:
    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.store_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_SCHEMA)

    def _audit(self, snapshot_id, underlying, status, rows=0, error=None):
        self.con.execute(
            "INSERT INTO ingest_runs (snapshot_id, underlying, recorded_at, status, rows, error) VALUES (?,?,?,?,?,?)",
            [snapshot_id, underlying, datetime.now(timezone.utc).isoformat(), status, rows, error],
        )

    def write(self, snap: Snapshot, payload: dict | None = None, source: str = "anvil", chain: OptionChain | None = None) -> str:
        """Idempotently persist an analytics snapshot (+ optional cleaned chain). Returns id."""
        sid = snapshot_id_for(snap.underlying, snap.expiry, snap.timestamp, source)
        existed = self.con.execute("SELECT 1 FROM snapshots WHERE snapshot_id = ?", [sid]).fetchone()
        try:
            self.con.execute(
                "INSERT INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (snapshot_id) DO NOTHING",
                [
                    sid, snap.underlying, snap.timestamp, snap.expiry, source, snap.spot,
                    snap.pcr_oi, snap.pcr_volume, snap.max_pain, snap.total_gex,
                    snap.zero_gamma_flip, snap.expected_move_1sigma, snap.atm_iv, snap.regime,
                    json.dumps(payload or snap.extra),
                ],
            )
            n = self.write_chain(sid, chain) if chain is not None else 0
            self._audit(sid, snap.underlying, "duplicate" if existed else "ok", n)
        except Exception as e:  # pragma: no cover - defensive
            self._audit(sid, snap.underlying, "error", 0, str(e))
            raise
        return sid

    def write_chain(self, snapshot_id: str, chain: OptionChain) -> int:
        n = 0
        for r in chain.rows:
            self.con.execute(
                "INSERT INTO chain_rows VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (snapshot_id, strike, option_type) DO NOTHING",
                [snapshot_id, chain.underlying, chain.timestamp, chain.expiry, r.strike,
                 r.option_type.value, r.ltp, r.oi, r.oi_change, r.volume, r.iv],
            )
            n += 1
        return n

    def count(self, underlying: str | None = None) -> int:
        if underlying:
            return self.con.execute("SELECT count(*) FROM snapshots WHERE underlying = ?", [underlying]).fetchone()[0]
        return self.con.execute("SELECT count(*) FROM snapshots").fetchone()[0]

    def latest(self, underlying: str, n: int = 10) -> list[tuple]:
        return self.con.execute(
            "SELECT ts, spot, total_gex, zero_gamma_flip, regime FROM snapshots "
            "WHERE underlying = ? ORDER BY ts DESC LIMIT ?",
            [underlying, n],
        ).fetchall()

    def latest_payload(self, underlying: str, before_ts: str | None = None) -> dict | None:
        """The most recent stored analytics payload (the baseline for 'what changed').

        ``before_ts`` excludes the current snapshot so a same-run diff has a real prior.
        Timestamps are compared as timezone-aware datetimes (snapshots are anchored to 15:30
        IST while a live read may be UTC, so a naive string compare would misorder them)."""
        rows = self.con.execute(
            "SELECT ts, payload FROM snapshots WHERE underlying = ? ORDER BY ts DESC LIMIT 100",
            [underlying],
        ).fetchall()
        if not rows:
            return None

        def _parse(s):
            try:
                dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                return None

        cutoff = _parse(before_ts) if before_ts else None
        best_ts, best_payload = None, None
        for ts, payload in rows:
            t = _parse(ts)
            if t is None or (cutoff is not None and t >= cutoff):
                continue
            if best_ts is None or t > best_ts:
                best_ts, best_payload = t, payload
        return json.loads(best_payload) if best_payload else None

    def spot_series(self, underlying: str) -> list[tuple[str, float]]:
        """Recorded (ts, spot) ticks for an underlying, ascending — the input the bar aggregator
        rolls into OHLC bars (turns the unbuyable recorded spot history into momentum bars)."""
        rows = self.con.execute(
            "SELECT ts, spot FROM snapshots WHERE underlying = ? AND spot IS NOT NULL ORDER BY ts",
            [underlying],
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def iv_history(self, underlying: str) -> list[float]:
        rows = self.con.execute(
            "SELECT atm_iv FROM snapshots WHERE underlying = ? AND atm_iv IS NOT NULL ORDER BY ts", [underlying]
        ).fetchall()
        return [r[0] for r in rows]

    def audit_log(self, n: int = 20) -> list[tuple]:
        return self.con.execute(
            "SELECT recorded_at, underlying, snapshot_id, status, rows FROM ingest_runs ORDER BY run_id DESC LIMIT ?", [n]
        ).fetchall()

    def export_parquet(self, out_dir: str) -> str:
        """Export the cleaned chain time-series to Parquet, partitioned by underlying (the moat)."""
        os.makedirs(out_dir, exist_ok=True)
        self.con.execute(
            f"COPY (SELECT * FROM chain_rows) TO '{out_dir}' (FORMAT PARQUET, PARTITION_BY (underlying), OVERWRITE_OR_IGNORE)"
        )
        return out_dir

    def close(self) -> None:
        self.con.close()
