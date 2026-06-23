"""M1 regression: the app SQLite engine must run in WAL with a busy_timeout.

Without this, the live supervisor's background writes collided with API reads under SQLite's default
database-wide lock and every authenticated endpoint 500'd intermittently with
``sqlite3.OperationalError: database is locked`` (see anvil/docs/TIPS_REBUILD.md)."""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from anvil.db import engine as dbengine


def test_sqlite_engine_uses_wal_and_busy_timeout(tmp_path):
    eng = dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'wal.db').as_posix()}")

    async def _probe():
        async with eng.connect() as conn:
            jm = (await conn.execute(text("PRAGMA journal_mode"))).scalar()
            bt = (await conn.execute(text("PRAGMA busy_timeout"))).scalar()
            return jm, bt

    journal_mode, busy_timeout = asyncio.run(_probe())
    assert str(journal_mode).lower() == "wal"
    assert int(busy_timeout) == 30000
