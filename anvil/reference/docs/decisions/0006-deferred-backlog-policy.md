# 0006 — Deferred-backlog policy

- **Date:** 2026-06-17
- **Status:** Accepted

## Context
At the Phase 0 plan gate we deliberately chose the lightweight option on several axes (offline-first
data, lightweight storage, static frontend, Docker-pinned Python) and scoped the session to Phase 0
only. Those deferrals must not be lost.

## Decision
Maintain a single tracked backlog at [`docs/PHASE1_BACKLOG.md`](../PHASE1_BACKLOG.md) capturing
**everything consciously deferred** — both the "full" option behind each Phase 0 choice and the
remaining roadmap pillars (Phases 1–6). Update it whenever a deferral is made or resolved.

## Why
A durable, in-repo record means future sessions inherit the deferred work and the reasoning, rather
than rediscovering it.

## Consequences
`PHASE1_BACKLOG.md` is the canonical "what's next / what we skipped and why" document.

## Revisit when
Each phase kickoff — promote items out of the backlog as they are built.
