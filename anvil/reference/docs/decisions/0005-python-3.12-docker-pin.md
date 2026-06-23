# 0005 — Pin Python 3.12 in Docker; record the future-price derivation limitation

- **Date:** 2026-06-17
- **Status:** Accepted

## Context
The host runs Python 3.14.4 (bleeding edge). Quant wheels (`py_vollib`, `scipy`, later
`lightgbm`/`arch`) may not yet ship cp314 builds, which would break installs and undermine the
"reproducible" requirement. Separately, NSE's option-chain payload exposes `underlyingValue`
(spot), but Black-76 needs the **futures price**.

## Decision
- Run the entire backend (dev, test, CI) in a Docker image pinned to **`python:3.12-slim`** with
  dependencies installed from `pyproject.toml`; capture the resolved versions into
  `backend/requirements.lock` (`pip freeze`) for reproducibility.
- For the futures price in Phase 0: **prefer recording the real NSE future** alongside the chain
  (`future_price_source = "nse_futures"`). When only the chain is available, derive a **tagged**
  cost-of-carry forward `F = spot · e^{(r−q)·t}` (q≈0 for short-dated NIFTY) and set
  `future_price_source = "derived_cost_of_carry"` so every Greek is auditable.

## Why
- A pinned 3.12 container sidesteps wheel gaps and makes every run reproducible regardless of host.
- Tagging the future-price source keeps the data honest and makes the Phase 1 swap to Kite's real
  future a one-line change in the adapter.

## Consequences
- Native execution on the host Python is deferred until 3.14 quant wheels land (Docker 3.12 remains
  the baseline regardless). Tracked in `docs/PHASE1_BACKLOG.md`.
- Greeks computed from a derived forward inherit its assumptions; flagged via the source tag.

## Revisit when
Kite Connect supplies the real future (Phase 1), or cp314 wheels for the quant stack are available.
