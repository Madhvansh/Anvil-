# ADR 0003 — Pin Python 3.12 in Docker for dev/test/CI

**Date:** 2026-06-18 · **Status:** Accepted

## Context
The host runs Python 3.14. The core engine + tests run fine on 3.14, but broker SDKs we need in
M4 — notably **`growwapi` (supports ≤3.13)** and `kiteconnect` — and some quant wheels lag the
newest interpreter.

## Decision
Provide a **`python:3.12-slim` Docker image** (+ docker-compose) as the canonical dev/test/CI
runtime, while keeping the package `requires-python = ">=3.11"` so it still runs natively on the
host where possible. CI builds the image, lints (ruff), runs pytest, and runs the offline demo
smoke test.

## Consequences
- Reproducible runs regardless of host interpreter; unblocks `growwapi`/`kiteconnect` in M4.
- Native 3.14 remains usable for the engine; broker-live work happens in the container.
