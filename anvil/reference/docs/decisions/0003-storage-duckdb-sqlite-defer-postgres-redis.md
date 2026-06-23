# 0003 — Storage: DuckDB + Parquet and SQLite; defer Postgres/Timescale + Redis

- **Date:** 2026-06-17
- **Status:** Accepted

## Context
`PROJECT_SPEC.md` §4 targets Postgres + TimescaleDB (live/operational), DuckDB + Parquet
(backtest data lake), and Redis (cache). Standing all of that up for a single-snapshot Phase 0
slice is disproportionate setup before anything runs.

## Decision
Phase 0 uses only:
- **DuckDB + Parquet** for chain snapshots and computed Greeks (columnar, file-based, no server).
- **SQLite** for operational metadata (instruments, snapshot registry, ingest-run audit).

No Postgres/Timescale, no Redis yet.

## Why
- Zero-infra, file-based stores run immediately and keep the demo + CI hermetic.
- DuckDB+Parquet is already the spec's choice for the historical lake, so it carries forward
  unchanged.

## Consequences
- Postgres + TimescaleDB (live time-series) and Redis (quote/chain cache) are deferred to Phase 1,
  where ingest volume and live caching justify them. The SQLite metadata schema is intentionally
  small to make that migration easy. Tracked in `docs/PHASE1_BACKLOG.md`.

## Revisit when
Phase 1 introduces continuous live ingestion and a cross-broker risk book that needs concurrent
writes and caching.
