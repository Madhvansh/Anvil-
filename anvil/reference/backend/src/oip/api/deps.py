"""FastAPI dependencies — built fresh per request from current settings (no hidden caching)."""

from __future__ import annotations

from collections.abc import Iterator

from ..calibration.ledger import CalibrationLedger
from ..config import get_settings
from ..data.fixture_replay import FixtureDataSource
from ..data.nse_public import NsePublicDataSource
from ..data.source import DataSource
from ..storage.duck import DuckStore
from ..storage.sqlite_meta import SqliteMeta


def get_datasource() -> DataSource:
    settings = get_settings()
    if settings.datasource == "nse_public":
        return NsePublicDataSource()
    return FixtureDataSource()


def get_store() -> DuckStore:
    # Stateless: opens/closes its own DuckDB connection per query, so no teardown needed.
    return DuckStore(get_settings().snapshots_dir)


def get_meta() -> Iterator[SqliteMeta]:
    # Generator dependency so FastAPI closes the SQLite connection after each request.
    meta = SqliteMeta(get_settings().sqlite_path)
    try:
        yield meta
    finally:
        meta.close()


def get_ledger() -> Iterator[CalibrationLedger]:
    # Generator dependency so FastAPI closes the DuckDB connection after each request.
    ledger = CalibrationLedger(get_settings().calibration_path)
    try:
        yield ledger
    finally:
        ledger.close()
