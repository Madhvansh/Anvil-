"""DuckDB + Parquet store for chain snapshots and computed Greeks.

Each snapshot is one Parquet file per dataset, partitioned by underlying and snapshot date:
    <snapshots_dir>/chain/underlying=NIFTY/snapshot_date=2026-06-12/<snapshot_id>.parquet
    <snapshots_dir>/greeks/underlying=NIFTY/snapshot_date=2026-06-12/<snapshot_id>.parquet
Reads use DuckDB SQL over the Parquet glob, filtered/joined by snapshot_id. Timestamps and dates
are stored as ISO strings so the round-trip is exact (reproducibility) and JSON-trivial.
"""

from __future__ import annotations

import math
from datetime import date as _date
from datetime import datetime as _datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from ..domain.models import GreeksResult, OptionChain

# Columns that are logically integers but may arrive as float64 if a Parquet column held nulls.
_INT_FIELDS = {"oi", "volume"}

_CHAIN_COLUMNS = [
    "snapshot_id", "underlying", "exchange", "snapshot_ts", "expiry", "strike", "option_type",
    "last_price", "bid", "ask", "oi", "volume", "iv_source", "spot", "future_price",
    "future_price_source", "risk_free_rate",
]
_GREEKS_COLUMNS = [
    "snapshot_id", "underlying", "snapshot_date", "expiry", "strike", "option_type",
    "iv_used", "t_years", "price_model", "engine_version", "price", "delta", "gamma",
    "theta_per_day", "vega_per_pct", "rho",
]


def _clean(value):
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        f = float(value)
        return None if math.isnan(f) else f
    if isinstance(value, float) and math.isnan(value):
        return None
    # Datetimes/dates (incl. pandas.Timestamp) → ISO strings so nothing JSON-unserializable escapes.
    if isinstance(value, (pd.Timestamp, _datetime, _date)):
        return None if pd.isna(value) else value.isoformat()
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    out: list[dict] = []
    for row in df.to_dict("records"):
        rec: dict = {}
        for k, v in row.items():
            cv = _clean(v)
            # Keep nullable integer columns as ints even after a null-induced float promotion.
            if k in _INT_FIELDS and isinstance(cv, float) and cv.is_integer():
                cv = int(cv)
            rec[k] = cv
        out.append(rec)
    return out


class DuckStore:
    def __init__(self, snapshots_dir: Path):
        self._dir = Path(snapshots_dir)

    # ---- paths -------------------------------------------------------------
    def _path(self, dataset: str, underlying: str, snapshot_date: str, snapshot_id: str) -> Path:
        return (
            self._dir / dataset / f"underlying={underlying}"
            / f"snapshot_date={snapshot_date}" / f"{snapshot_id}.parquet"
        )

    def _glob(self, dataset: str) -> str:
        return str(self._dir / dataset / "**" / "*.parquet")

    def _has_files(self, dataset: str) -> bool:
        return any((self._dir / dataset).rglob("*.parquet")) if (self._dir / dataset).exists() else False

    # ---- writes ------------------------------------------------------------
    def write_snapshot(self, snapshot_id: str, chain: OptionChain) -> str:
        snapshot_ts = chain.snapshot_ts.isoformat()
        snapshot_date = chain.snapshot_ts.date().isoformat()
        rows: list[dict] = []
        for row in chain.rows:
            for leg in (row.call, row.put):
                if leg is None:
                    continue
                rows.append({
                    "snapshot_id": snapshot_id,
                    "underlying": chain.underlying,
                    "exchange": chain.exchange.value,
                    "snapshot_ts": snapshot_ts,
                    "expiry": row.expiry.isoformat(),
                    "strike": float(row.strike),
                    "option_type": leg.option_type.value,
                    "last_price": leg.last_price,
                    "bid": leg.bid,
                    "ask": leg.ask,
                    "oi": leg.oi,
                    "volume": leg.volume,
                    "iv_source": leg.iv_source,
                    "spot": chain.spot,
                    "future_price": chain.future_price,
                    "future_price_source": chain.future_price_source.value,
                    "risk_free_rate": chain.risk_free_rate,
                })
        df = pd.DataFrame(rows, columns=_CHAIN_COLUMNS)
        path = self._path("chain", chain.underlying, snapshot_date, snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return str(path)

    def write_greeks(self, snapshot_id: str, chain: OptionChain, results: list[GreeksResult]) -> str:
        snapshot_date = chain.snapshot_ts.date().isoformat()
        rows = [{
            "snapshot_id": snapshot_id,
            "underlying": chain.underlying,
            "snapshot_date": snapshot_date,
            "expiry": g.expiry.isoformat(),
            "strike": float(g.strike),
            "option_type": g.option_type.value,
            "iv_used": g.iv_used,
            "t_years": g.t_years,
            "price_model": g.price_model,
            "engine_version": g.engine_version,
            "price": g.price,
            "delta": g.delta,
            "gamma": g.gamma,
            "theta_per_day": g.theta_per_day,
            "vega_per_pct": g.vega_per_pct,
            "rho": g.rho,
        } for g in results]
        df = pd.DataFrame(rows, columns=_GREEKS_COLUMNS)
        path = self._path("greeks", chain.underlying, snapshot_date, snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, index=False)
        return str(path)

    # ---- reads -------------------------------------------------------------
    def read_chain(self, snapshot_id: str) -> list[dict]:
        if not self._has_files("chain"):
            return []
        con = duckdb.connect()
        try:
            df = con.execute(
                f"SELECT * FROM read_parquet('{self._glob('chain')}', hive_partitioning=false) "
                "WHERE snapshot_id = ? ORDER BY strike, option_type",
                [snapshot_id],
            ).df()
        finally:
            con.close()
        return _records(df)

    def read_greeks(self, snapshot_id: str) -> list[dict]:
        if not self._has_files("greeks"):
            return []
        con = duckdb.connect()
        try:
            df = con.execute(
                f"SELECT * FROM read_parquet('{self._glob('greeks')}', hive_partitioning=false) "
                "WHERE snapshot_id = ? ORDER BY strike, option_type",
                [snapshot_id],
            ).df()
        finally:
            con.close()
        return _records(df)

    def read_chain_with_greeks(self, snapshot_id: str) -> list[dict]:
        """Join chain legs with their Greeks on (snapshot_id, strike, option_type)."""
        if not self._has_files("chain"):
            return []
        if not self._has_files("greeks"):
            return self.read_chain(snapshot_id)  # Greeks not computed yet
        con = duckdb.connect()
        try:
            df = con.execute(
                f"""
                SELECT c.*,
                       g.iv_used, g.t_years, g.price_model, g.engine_version, g.price,
                       g.delta, g.gamma, g.theta_per_day, g.vega_per_pct, g.rho
                FROM read_parquet('{self._glob('chain')}', hive_partitioning=false) c
                LEFT JOIN read_parquet('{self._glob('greeks')}', hive_partitioning=false) g
                  ON c.snapshot_id = g.snapshot_id
                 AND c.strike = g.strike
                 AND c.option_type = g.option_type
                 AND c.expiry = g.expiry
                WHERE c.snapshot_id = ?
                ORDER BY c.expiry, c.strike, c.option_type
                """,
                [snapshot_id],
            ).df()
        finally:
            con.close()
        return _records(df)
