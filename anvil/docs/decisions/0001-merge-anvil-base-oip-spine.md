# ADR 0001 — Merge: Anvil base + OIP correctness spine

**Date:** 2026-06-18 · **Status:** Accepted

## Context
Two versions of the product existed: **Anvil** (rich analytics — GEX/flip, Breeden-Litzenberger
implied distribution, beta-weighted Greeks, regime, OI/vol — plus connectors, API, CLI) and
**OIP** (a correct **Black-76-on-futures** engine, finite-difference/vollib-validated tests,
deterministic Parquet+SQLite storage, Docker/CI/ADRs — but none of the analytics). Code-level
audits found Anvil priced on **spot (BSM)** with the `future_price` field unused (a real
correctness bug), and that both dossiers overstated test counts.

## Decision
Use **Anvil as the base** (it owns the revenue-driving analytics + connectors that would take
weeks to rebuild) and **transplant OIP's correctness spine and discipline**: the Black-76 engine,
the finite-diff/parity/py_vollib/IV-round-trip validation bar, deterministic storage, futures-source
tagging, and Docker-3.12/CI/ADRs. Grafting the 186-line engine into Anvil is hours; the reverse is
weeks.

## Consequences
- Greeks are now futures-correct (see ADR 0002); the analytics were re-pointed to a forward `F`.
- One git repo, containerized, CI-gated.
- Net-new work (absent in both) — calibration ledger, live auth, UI, agent — is built on this base.
