# Tips Engine — Fix & Rebuild (live, full-analysis, stock + index)

**Status doc — keep updated at the end of every milestone.** This is the durable context for the
tips rebuild kicked off 2026-06-23 after the owner found the tips feature unusable. Read this first
when resuming.

---

## Why this exists (the complaint)

After 12 "waves," the tips feature — the heart of Anvil — was effectively useless. From the latest
screenshots (`screenshots evaluations latest/`) and the live server log (`anvil/go_live.log`):

- **"Live prediction — NIFTY" → "Couldn't load tips."** (`/api/tips/{u}` 500s).
- **"Stock tips — cross-sectional BUY/SELL"**: 10 generic names, **all identical 62.0%**, all 5d,
  **"as of 2025-11-28"** (~7 months stale). Momentum-only, flat-confidence, chain-free picks.
- **Edge-proven / Watchlist / Track record empty** (0 / — / 0 / —).
- **Momentum index-only** (NIFTY), 1 timeframe voting; no per-stock momentum.
- Everything badged PAPER; nothing feels live.

**Directive:** make tips (stock AND index) genuinely useful, accurate, and live — driven by the full
analysis stack (chain, greeks, OI, momentum, dealer flow). Stocks must be **dynamically selected**
(most-liquid + highest-momentum + maximum monetization opportunity — *not* a fixed list),
cross-sectionally ranked with real differentiated conviction, and update live. Market-closed → show
freshest available, timestamped. Ship live now + run backtests in parallel for measured edge.

---

## Root-cause diagnosis (confirmed against `anvil/go_live.log` — primary evidence)

1. **`sqlite3.OperationalError: database is locked`** — the dominant failure, hitting nearly every
   authenticated endpoint intermittently (tips, momentum, paper, scenario, decision-brief,
   portfolio-risk…). One `/api/tips/NIFTY` took **15.7s** before succeeding (log line 1785). Cause:
   `anvil/anvil/db/engine.py` built the async SQLite engine with no WAL, no `busy_timeout`, no
   `connect_args`. Every request commits a write (autoflush in the `current_user` auth dep), so the
   live supervisor's background writes collided with API reads under SQLite's default DB-wide lock.

2. **`Out of range float values are not JSON compliant: nan`** (log lines 3082, 3245) — 500s
   `/api/tips/track-record` and `/api/tips/trust-dial`. `backtest/aggregate.py::validate_cells`
   stores `float("nan")` for under-sampled cells; the tips router returned them raw and Starlette's
   `allow_nan=False` encoder threw. Fix: route through the existing `engine/util.py::json_safe`.

3. **Stock tips stale/flat/chain-free by design.** `tips/equities.py` ranks via
   `factors/equities.py::equity_signals` = 12-1 momentum + 1w reversal + futures-OI only (no chain/
   greeks/IV/skew/GEX/multi-tf). Confidence `min(0.62, 0.5+0.12·|score|)` → clusters at 0.62.
   `/api/tips/equities` serves most-recent `IssuedTipStore` rows → only as fresh as the last nightly
   EOD run. No live stock path (`run_intraday` is index-only).

### What makes the rebuild feasible (already present)

- `ingest/upstox.py` `get_chain(sym)` / `get_candles(sym, tf)` accept **equity** symbols too (full
  greeks/IV/OI + multi-tf candles). Live token configured (`.env`: `ANVIL_PRIMARY_SOURCE=upstox`).
- The index already runs the full stack: `tips/pipeline.py::tips_for_chain` → `compute_factors`
  (chain_analytics, dealer_flow GEX, momentum via `tips/series.py::build_series_block`) → regime →
  gated candidates → `tips/predict.py::predict_for_chain`. `tips/momentum.py::momentum_for_chain`
  already accepts "stock OR index". **We route stocks through this same spine.**
- `tips/equities.py::discover_universe` already ranks F&O stocks by option volume (liquidity screen).

---

## Milestones

- **M0 — context doc + reproduce** — ✅ this file. 500 classes evidenced in `go_live.log`.
- **M1 — make the surface work live, never 500** — ✅ DONE (see below).
- **M2 — real, live, chain-driven stock tips w/ dynamic universe** — ⬜ TODO.
- **M3 — cross-sectional ranking quality** — ⬜ TODO.
- **M4 — per-stock momentum + UI stock selection + rich cards** — ⬜ TODO.
- **M5 — honest accuracy / measured-edge wiring (backtest into default store)** — ⬜ TODO.
- **M6 — verification + regression** — ⬜ ongoing.

### M1 — done (2026-06-23)
Changes (the ~30-line MVP that clears the 500 storm):
- `db/engine.py` — `init_engine` now sets `connect_args={"timeout":30}` for sqlite and a `connect`
  event hook issuing `PRAGMA journal_mode=WAL; synchronous=NORMAL; busy_timeout=30000`
  (`_enable_sqlite_concurrency`). Postgres path untouched.
- `api/routers/tips.py` — import `json_safe`; wrap returns of `_track_record`, `_trust_dial_payload`,
  `_feed`, `_equities`, `_compute_tips`. New `_open()` helper + `_compute_tips` degrades every overlay
  (validation store / ledger metrics / calibration service / meta-label) to None/{} on failure so the
  never-empty live prediction can't 500 on an overlay.
- `api/routers/momentum.py` — import `json_safe`; `_open()` resilience for BarStore/SnapshotStore/
  TipValidationStore; wrap payload in `json_safe`.
- `tips/predict.py` — calibration `calibrate`/`is_calibrated` block wrapped in try/except → degrade to
  identity (raw confidence stands).

Verify: `cd anvil && .venv\Scripts\python -m pytest -q` green; under `go-live` + concurrent hits all
of `/api/tips/{u}`, `/api/tips/equities`, `/api/tips/track-record`, `/api/momentum/{u}` return 200.

---

## Config flags to add (M2+)
`stock_tips_live` (True), `stock_universe_top_n` (~15), `stock_cockpit_enabled` (False),
`stock_refresh_ttl_s` (60), `stock_cockpit_cadence_s` (120), `stock_refresh_concurrency` (4).

## Honesty rails (do NOT break)
- HEADLINE only when a validation cell is `headline_eligible` (measured, OOS, post-cost). No fabricated
  accuracy. Calibration is display-only (degrade to identity), never feeds the gate or sizing.
- Provenance always reports the real source; demo never presented as live.
