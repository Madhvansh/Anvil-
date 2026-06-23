# 0001 — Stack: Python 3.12 + FastAPI backend, static-page frontend for Phase 0

- **Date:** 2026-06-17
- **Status:** Accepted

## Context
The architecture and stack were left open by `NORTH_STAR.md` / `PROJECT_SPEC.md`, to be proposed
at the plan gate. Phase 0 is a thin vertical slice (ingest → Black-76 Greeks → store → query →
display) that must be runnable today. `PROJECT_SPEC.md` names Python/FastAPI for the backend and
Next.js + React + Tailwind for the frontend.

## Decision
- **Backend:** Python + FastAPI. Python is non-negotiable for the quant stack (`py_vollib`,
  `numpy`/`scipy`, later `arch`/`lightgbm`); FastAPI matches the spec and gives REST + WebSocket
  headroom for later phases.
- **Frontend (Phase 0 only):** a small static HTML/JS page served directly by FastAPI. Phase 0's
  display requirement is a single read-only chain+Greeks table; a Node build/container is not
  worth it yet.

## Why
- One container, no Node build → the slice runs immediately and CI stays simple.
- The page consumes the same JSON API contract the eventual Next.js app will use, so nothing is
  thrown away.

## Consequences
- The full **Next.js + React + Tailwind** frontend (with charting for the risk book and the
  reliability diagrams) is deferred to Phase 1. Tracked in `docs/PHASE1_BACKLOG.md`.

## Revisit when
Phase 1 introduces interactivity (risk-book scenario grids, live updates) that a static page
can't serve cleanly.
