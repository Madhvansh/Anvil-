# Deferred backlog — everything skipped past Phase 0 (kept on purpose)

This is the canonical record of work consciously deferred during the Phase 0 build, so nothing is
lost. It has two parts: (A) the "full" option behind each lightweight choice we made at the plan
gate, and (B) the remaining roadmap pillars. Promote items out as they are built; see
`docs/decisions/0006-deferred-backlog-policy.md`.

_Last updated: 2026-06-17 (end of Phase 0)._

---

## A. Full options behind the Phase 0 choices we made

Each row is a place where we chose the lightweight/recommended path for Phase 0 and parked the
fuller version. The "feature kept as-is for next phase" column is the thing to build later.

### A1. Live broker data  ← deferred from the *Offline-first* data choice ([ADR 0002](decisions/0002-offline-first-data-adapters.md))
- **Kite Connect ingestion** — implement a `KiteDataSource(DataSource)`: API key/secret, login
  flow + access-token handling, historical chain / instruments, and the **real futures price**
  (replaces the derived cost-of-carry forward — see [ADR 0005](decisions/0005-python-3.12-docker-pin.md)).
- **Groww connector** — `GrowwDataSource(DataSource)` via its MCP connector for live positions/quotes.
- **Activate broker validation as a gate** — capture broker-shown Greeks for a few NIFTY/BANKNIFTY
  strikes into `backend/tests/fixtures/broker_greeks_nifty.json`, then make the `broker_validation`
  pytest marker **required** in CI (it is non-gating today; format already finalized).
- *Kept as-is:* the `DataSource` protocol, so all of the above are drop-in implementations.

### A2. NSE-public hardening  ← deferred from the same choice
- Promote `NsePublicDataSource` from capture-only to a resilient live source: cookie/session
  warm-up, retry/backoff, rate-limit handling, schema-drift tolerance, and recording the real NSE
  **futures** quote alongside the chain.

### A3. Full storage stack  ← deferred from the *Lightweight storage* choice ([ADR 0003](decisions/0003-storage-duckdb-sqlite-defer-postgres-redis.md))
- **Postgres + TimescaleDB** for live/operational time-series; migrate the SQLite metadata schema
  (`instruments`, `snapshots`, `ingest_runs`) and define the live-vs-historical boundary.
- **Redis** for caching live quotes/chains.
- *Kept as-is:* DuckDB + Parquet remains the historical/backtest lake (already the spec's choice).

### A4. Full Next.js frontend  ← deferred from the *Static page* choice ([ADR 0001](decisions/0001-stack-python-fastapi-static-frontend.md))
- **Next.js + React + Tailwind** app reusing the existing JSON API contract.
- Charting: `lightweight-charts` (price/IV), Plotly/D3 (distributions, **reliability diagrams** for
  the calibration surface in Phase 3).
- Auth (Auth.js/Clerk) when multi-user.

### A5. Native Python env  ← deferred from the *Docker, Python 3.12* choice ([ADR 0005](decisions/0005-python-3.12-docker-pin.md))
- Revisit running natively once cp314 wheels for the quant stack (`py_vollib`, `arch`, `lightgbm`,
  `scipy`) are available. Docker-3.12 stays the reproducible baseline regardless.

### A6. Greeks follow-ups  ← deferred from the Black-76 engine ([ADR 0004](decisions/0004-greeks-black76-pyvollib.md))
- Higher-order Greeks (vanna, vomma, charm) when the risk book needs them.
- Replace the derived forward with the broker/exchange real future everywhere it is consumed.

---

## B. Remaining roadmap pillars (PROJECT_SPEC §3 / §7)

- **Phase 1 — Cross-broker unified risk book.** Consolidate Kite + Groww positions; net Greeks;
  **beta-weighted delta to Nifty**; scenario grid (spot × IV) + **Monte-Carlo P&L** distribution
  and tail risk; margin/capital efficiency. *Deliverable: unified net Greeks + expected move across
  both brokers, reconciling to a hand-computed fixture within tolerance.* (Built on the Phase 0
  Black-76 engine.)
- **Phase 2 — Honest backtesting lab.** Walk-forward / out-of-sample by construction;
  **look-ahead & survivorship-bias guards implemented as tests that FAIL the build**; cost/slippage/
  liquidity modeling; MLflow experiment tracking; regime-conditional performance. *Deliverable: a
  known look-ahead violation makes the run fail, not warn.*
- **Phase 3 — Calibrated forecast engine + calibration service.** Ensemble of implied
  (straddle/IV-term/skew) + statistical (GARCH via `arch`, regime classification) + ML
  (LightGBM/XGBoost) families; outputs are probability bands, probability-of-touch, directional
  probability, expected-move cone — **never point targets**; a **live calibration dashboard** (Brier
  score, log loss, reliability diagrams, band coverage) per horizon and regime. *This is the
  product's differentiating heart.*
- **Phase 4 — Flow & event intelligence.** NSE participant-wise OI (FII/DII/Pro/Client) decoded
  into plain-language narratives; FII index-futures long/short ratio; **unusual-options-activity
  scanner**; OI-buildup classification; event calendar (Budget/RBI/earnings/expiry/F&O ban) +
  **IV-crush guard** against long-premium entries into expected post-event IV collapse; vol-regime
  classifier.
- **Phase 5 — Copilot + behavioral journal.** Claude-native analyst doing tool-use over the API +
  broker MCP, grounded in the live book/chain/models; behavioral trade journal surfacing the user's
  own decision leaks (loss aversion, IV-timing errors, holding winners/losers too long).
- **Phase 6 — Hardening & beta.** Alerts, auth, deploy (Docker on VPS/cloud), structured logging,
  onboard a handful of beta users.

---

## Hard rails that every future phase must keep honoring
- Forecasts are **probabilities with a live calibration score** — never point targets or "accuracy"
  claims. Disclaimers on every forecast surface.
- Quant code is **test-first**; nothing merges without a passing check.
- Backtester look-ahead & survivorship guards are **failing tests**, not warnings.
- Greeks are **Black-76 on the futures price**, validated against broker values.
