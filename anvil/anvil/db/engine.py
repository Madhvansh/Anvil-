"""Async SQLAlchemy engine + session factory for the app/OLTP tier.

URL comes from ``SETTINGS.database_url`` (``ANVIL_DATABASE_URL``): Postgres in prod
(``postgresql+asyncpg://…``), ``sqlite+aiosqlite`` locally so dev/tests need no Docker.
``init_engine(url)`` lets tests point at a throwaway database without touching env.

The DuckDB/Parquet research + calibration moat is *not* here — it keeps its own
connections in ``store/`` and ``ledger/``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ..config import SETTINGS
from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _enable_sqlite_concurrency(dbapi_connection, _record) -> None:
    """Per-connection SQLite PRAGMAs so concurrent readers and the background writer (the live
    supervisor) don't collide on the default database-wide lock.

    Without this, SQLite's default ``DELETE`` journal takes an exclusive lock on every write, and a
    reader colliding with the supervisor's write fails *immediately* with ``database is locked``
    (the root cause of the intermittent 500s across every authenticated endpoint). WAL lets readers
    and a single writer proceed concurrently; ``busy_timeout`` makes any remaining contention WAIT
    (up to 30s) instead of erroring. ``synchronous=NORMAL`` is the safe, fast pairing for WAL."""
    cur = dbapi_connection.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
    finally:
        cur.close()


def init_engine(url: str | None = None) -> AsyncEngine:
    """(Re)build the engine + sessionmaker. Tests pass a temp URL to isolate state."""
    global _engine, _sessionmaker
    resolved = url or SETTINGS.database_url
    kwargs: dict = {"future": True}
    is_sqlite = resolved.startswith("sqlite")
    if is_sqlite:
        # The DBAPI-level lock wait (acquiring the very first lock); the per-connection PRAGMA
        # busy_timeout below covers waits after a connection is established.
        kwargs["connect_args"] = {"timeout": 30}
    _engine = create_async_engine(resolved, **kwargs)
    if is_sqlite:
        event.listen(_engine.sync_engine, "connect", _enable_sqlite_concurrency)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def get_engine() -> AsyncEngine:
    if _engine is None:
        init_engine()
    assert _engine is not None
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    if _sessionmaker is None:
        init_engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yields a session, commits on success, rolls back on error."""
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """Create every table from the ORM metadata (dev/tests; prod uses Alembic)."""
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
