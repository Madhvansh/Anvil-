"""Append-only calibration ledger (DuckDB-backed, reproducible).

Log a probabilistic forecast now; later resolve it against the realized value; the ledger derives
the binary outcome and scores calibration over all resolved forecasts. Reproducible because every
timestamp and id is caller-supplied (no hidden wall-clock) — re-logging the same forecast_id
replaces it idempotently, mirroring the deterministic-snapshot discipline elsewhere.

Forecast kinds and how the outcome is derived on resolve:
  - "prob_above"  : outcome = 1 if realized >  level_low
  - "prob_below"  : outcome = 1 if realized <  level_low
  - "prob_up"     : outcome = 1 if realized >  level_low   (level_low = reference price at forecast)
  - "prob_inside" : outcome = 1 if level_low <= realized <= level_high
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb

from . import scoring

_SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id   VARCHAR PRIMARY KEY,
    created_ts    VARCHAR NOT NULL,
    underlying    VARCHAR NOT NULL,
    horizon       VARCHAR,
    kind          VARCHAR NOT NULL,
    level_low     DOUBLE,
    level_high    DOUBLE,
    prob          DOUBLE NOT NULL,
    model_version VARCHAR,
    regime        VARCHAR,
    drivers       VARCHAR
);
CREATE TABLE IF NOT EXISTS outcomes (
    forecast_id    VARCHAR PRIMARY KEY,
    resolved_ts    VARCHAR NOT NULL,
    realized_value DOUBLE,
    outcome        INTEGER NOT NULL
);
"""


def _derive_outcome(kind: str, realized: float, level_low: float | None, level_high: float | None) -> int:
    if kind in ("prob_above", "prob_up"):
        return int(realized > (level_low if level_low is not None else 0.0))
    if kind == "prob_below":
        return int(realized < (level_low if level_low is not None else 0.0))
    if kind == "prob_inside":
        lo = level_low if level_low is not None else float("-inf")
        hi = level_high if level_high is not None else float("inf")
        return int(lo <= realized <= hi)
    raise ValueError(f"Unknown forecast kind: {kind!r}")


class CalibrationLedger:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(self.path))
        self.con.execute(_SCHEMA)

    # ---- writes ------------------------------------------------------------
    def log_forecast(
        self,
        *,
        forecast_id: str,
        underlying: str,
        kind: str,
        prob: float,
        created_ts: str,
        horizon: str | None = None,
        level_low: float | None = None,
        level_high: float | None = None,
        model_version: str | None = None,
        regime: str | None = None,
        drivers: dict | None = None,
    ) -> str:
        if kind not in ("prob_above", "prob_below", "prob_up", "prob_inside"):
            raise ValueError(f"Unknown forecast kind: {kind!r}")
        if not (0.0 <= prob <= 1.0):
            raise ValueError(f"prob must be in [0, 1], got {prob}")
        self.con.execute("DELETE FROM forecasts WHERE forecast_id = ?", [forecast_id])
        self.con.execute(
            "INSERT INTO forecasts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                forecast_id, created_ts, underlying.upper(), horizon, kind,
                level_low, level_high, prob, model_version, regime,
                json.dumps(drivers or {}),
            ],
        )
        return forecast_id

    def resolve(self, forecast_id: str, *, realized_value: float, resolved_ts: str) -> int:
        row = self.con.execute(
            "SELECT kind, level_low, level_high FROM forecasts WHERE forecast_id = ?",
            [forecast_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"No forecast {forecast_id!r} to resolve")
        outcome = _derive_outcome(row[0], realized_value, row[1], row[2])
        self.con.execute("DELETE FROM outcomes WHERE forecast_id = ?", [forecast_id])
        self.con.execute(
            "INSERT INTO outcomes VALUES (?, ?, ?, ?)",
            [forecast_id, resolved_ts, realized_value, outcome],
        )
        return outcome

    # ---- reads / scoring ---------------------------------------------------
    def resolved_pairs(self, underlying: str | None = None) -> list[tuple[float, int]]:
        sql = (
            "SELECT f.prob, o.outcome FROM forecasts f JOIN outcomes o "
            "USING (forecast_id)"
        )
        params: list = []
        if underlying:
            sql += " WHERE f.underlying = ?"
            params.append(underlying.upper())
        return [(float(p), int(o)) for p, o in self.con.execute(sql, params).fetchall()]

    def counts(self, underlying: str | None = None) -> tuple[int, int]:
        fsql, osql, params = "SELECT count(*) FROM forecasts", (
            "SELECT count(*) FROM forecasts f JOIN outcomes o USING (forecast_id)"
        ), []
        if underlying:
            fsql += " WHERE underlying = ?"
            osql += " WHERE f.underlying = ?"
            params = [underlying.upper()]
        n_f = self.con.execute(fsql, params).fetchone()[0]
        n_r = self.con.execute(osql, params).fetchone()[0]
        return int(n_f), int(n_r)

    def brier(self, underlying: str | None = None) -> float | None:
        return scoring.brier_score(self.resolved_pairs(underlying))

    def log_loss(self, underlying: str | None = None) -> float | None:
        return scoring.log_loss(self.resolved_pairs(underlying))

    def reliability(self, underlying: str | None = None, n_bins: int = 10):
        return scoring.reliability_bins(self.resolved_pairs(underlying), n_bins=n_bins)

    def summary(self, underlying: str | None = None) -> dict:
        n_f, n_r = self.counts(underlying)
        bins = self.reliability(underlying)
        return {
            "underlying": underlying,
            "n_forecasts": n_f,
            "n_resolved": n_r,
            "brier": self.brier(underlying),
            "log_loss": self.log_loss(underlying),
            "reliability": [
                {
                    "lo": b.lo, "hi": b.hi, "n": b.n,
                    "mean_predicted": b.mean_predicted, "observed_freq": b.observed_freq,
                }
                for b in bins
            ],
        }

    def close(self) -> None:
        self.con.close()
