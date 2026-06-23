"""Persisted, auditable calibrators — one DuckDB row per ``(target, source_class)``.

Parallel to ``tips.store.tip_validation`` and ``backtest.trials.experiment_trials`` (same
``store_path`` DB). The PK ``(target, source_class)`` IS the firewall: a ``tip_backtest`` conviction
map and a ``tip_live`` conviction map are different rows and can never overwrite each other, so a map
fit on out-of-sample history never silently drives live predictions. Every row carries its
OUT-OF-FOLD ``ece_before``/``ece_after`` (auditable), the identity-shrinkage ``lambda_blend`` actually
applied, the risk-coverage ``abstain_tau``, and the ``model_version`` freshness stamp.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

import duckdb

from ..config import SETTINGS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calibrators (
    target VARCHAR,
    source_class VARCHAR,
    kind VARCHAR,
    params JSON,
    n INTEGER,
    n_folds INTEGER,
    ece_before DOUBLE,
    ece_after DOUBLE,
    brier_before DOUBLE,
    brier_after DOUBLE,
    lambda_blend DOUBLE,
    abstain_tau DOUBLE,
    conformal JSON,
    fit_ts VARCHAR,
    model_version VARCHAR,
    PRIMARY KEY (target, source_class)
);
"""

_COLS = [
    "target", "source_class", "kind", "params", "n", "n_folds", "ece_before", "ece_after",
    "brier_before", "brier_after", "lambda_blend", "abstain_tau", "conformal", "fit_ts",
    "model_version",
]
_JSON_COLS = {"params", "conformal"}


@dataclass
class CalibratorRecord:
    target: str
    source_class: str
    kind: str
    params: dict = field(default_factory=dict)
    n: int = 0
    n_folds: int = 0
    ece_before: float = float("nan")
    ece_after: float = float("nan")
    brier_before: float = float("nan")
    brier_after: float = float("nan")
    lambda_blend: float = 1.0
    abstain_tau: float | None = None
    conformal: dict = field(default_factory=dict)
    fit_ts: str = ""
    model_version: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _row_to_record(row) -> CalibratorRecord:
    d = dict(zip(_COLS, row))
    for k in _JSON_COLS:
        v = d.get(k)
        d[k] = json.loads(v) if isinstance(v, str) else (v or {})
    return CalibratorRecord(**d)


class CalibratorStore:
    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.store_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_SCHEMA)

    def upsert(self, rec: CalibratorRecord) -> None:
        d = asdict(rec)
        vals = []
        for c in _COLS:
            v = d[c]
            vals.append(json.dumps(v) if c in _JSON_COLS else v)
        self.con.execute(
            f"INSERT OR REPLACE INTO calibrators ({','.join(_COLS)}) "
            f"VALUES ({','.join('?' for _ in _COLS)})",
            vals,
        )

    def get(self, target: str, source_class: str) -> CalibratorRecord | None:
        row = self.con.execute(
            f"SELECT {','.join(_COLS)} FROM calibrators WHERE target=? AND source_class=?",
            [target, source_class],
        ).fetchone()
        return _row_to_record(row) if row else None

    def all(self) -> list[dict]:
        rows = self.con.execute(f"SELECT {','.join(_COLS)} FROM calibrators").fetchall()
        return [_row_to_record(r).to_dict() for r in rows]

    def load_service(self):
        """Hydrate a read-only ``CalibrationService`` from the persisted rows."""
        from .service import CalibrationService

        rows = self.con.execute(f"SELECT {','.join(_COLS)} FROM calibrators").fetchall()
        return CalibrationService([_row_to_record(r) for r in rows])

    def close(self) -> None:
        self.con.close()
