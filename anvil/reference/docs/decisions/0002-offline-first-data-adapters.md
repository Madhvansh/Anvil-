# 0002 — Offline-first data via a DataSource protocol

- **Date:** 2026-06-17
- **Status:** Accepted

## Context
Live data needs paid broker credentials (Kite Connect) and connector setup (Groww); NSE's public
option-chain endpoint is free but flaky, rate-limited, and sometimes IP-blocked. Phase 0 must run
end-to-end with **zero credentials** and deterministically in CI.

## Decision
Define a single `DataSource` protocol (`fetch_chain`, `list_expiries`, `name`,
`requires_credentials`). Phase 0 ships two implementations:
- **`FixtureDataSource`** — the default. Reads committed JSON fixtures in `data/fixtures/`. Zero
  network, fully deterministic.
- **`NsePublicDataSource`** — capture-only helper for recording fresh fixtures (`record_fixture.py`).
  Marked `nse_live`; never gates the build.

All downstream code (pipeline, API) depends only on the protocol.

## Why
- Deterministic, credential-free CI and demos.
- Real Kite/Groww connectors become drop-in implementations of the same protocol — no downstream
  changes.

## Consequences
- Live broker ingestion (Kite, Groww) and NSE-public hardening are deferred to Phase 1. Tracked in
  `docs/PHASE1_BACKLOG.md`.
- The committed fixture is a snapshot, not live data; the UI shows the snapshot timestamp plainly.

## Revisit when
Kite/Groww credentials are available and the risk book needs live positions.
