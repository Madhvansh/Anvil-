# Options Intelligence Platform

Calibrated options-intelligence for Indian markets (NSE/BSE). We win on **trust, not hype**:
every forecast is a probability shown with its live calibration score — never a point target or
an "accuracy" claim. See [`NORTH_STAR.md`](NORTH_STAR.md) for the mission and
[`PROJECT_SPEC.md`](PROJECT_SPEC.md) for the full brief.

> **Disclaimer.** Everything this platform produces — including Greeks — is *computed analytics*
> and *probabilistic context*, **not investment advice**. No accuracy or guaranteed return is
> claimed anywhere.

## Status: Phase 0 — Foundation (thin vertical slice)

Phase 0 proves the pipe end-to-end with **zero credentials**:

```
fixture option chain → normalize → Black-76 Greeks (on the futures price) → store → query → display
```

- **Greeks** are computed locally with **Black-76** (Indian index options settle off futures),
  not pulled from any broker API. The engine is **test-first**: it was written against a failing
  suite of known-value, put-call-parity, finite-difference, and IV round-trip checks.
- **Offline-first**: data comes from committed JSON fixtures behind a `DataSource` protocol.
  Real Kite/Groww connectors plug into the same interface later (see
  [`docs/PHASE1_BACKLOG.md`](docs/PHASE1_BACKLOG.md)).
- **Storage**: DuckDB + Parquet (snapshots) and SQLite (metadata). No Postgres/Redis yet.

## Quick start (Docker, Python 3.12)

The backend runs in a container pinned to Python 3.12 (the host's 3.14 may lack some quant
wheels). Docker is the only prerequisite.

```bash
# 1. Build the image
docker compose build

# 2. Run the test suite (the merge gate)
docker compose run --rm backend pytest -m "unit or validation" --strict-markers -q

# 3. Run the end-to-end demo (ingest → Greeks → store → query → reproducibility self-check)
docker compose run --rm backend python scripts/demo_phase0.py --underlying NIFTY

# 4. Serve the API + page, then open http://localhost:8000/
docker compose up
```

### API

| Endpoint | Purpose |
|---|---|
| `GET /health` | Liveness + datasource + engine version |
| `GET /chain?underlying=NIFTY` | Latest chain snapshot with computed Greeks |
| `GET /chain/{snapshot_id}` | A specific stored snapshot (audit/reproducibility) |
| `GET /greeks?underlying=NIFTY&strike=22000&option_type=c` | Greeks for one leg |

Every response includes a `disclaimer` field.

## Layout

```
backend/   Python 3.12 + FastAPI; quant (Black-76), data adapters, storage, API, tests
data/      Committed fixtures (tracked) + runtime snapshots/SQLite (gitignored)
docs/      decisions/ (ADRs) + PHASE1_BACKLOG.md (everything deferred past Phase 0)
```

## Development without Docker

If you have a compatible Python (3.12 recommended) you can run the suite directly:

```bash
cd backend
pip install -e ".[dev]"
pytest -m "unit or validation" --strict-markers -q
```
