# Anvil — Roadmap & Backlog (post-merge)

Status legend: ✅ done · 🔜 next · ⏳ later

## Done
- ✅ **M1 — Black-76 correctness graft.** Futures-priced engine + forward resolver (source-tagged);
  GEX/flip, Breeden-Litzenberger, beta-weighted Greeks, regime, vol re-pointed to the forward;
  higher-order Greeks (vanna/charm/vomma) re-derived; **67 tests** incl. finite-difference, parity,
  IV round-trip (py_vollib agreement when installed). See ADR 0001, 0002.
- ✅ **M0 — Discipline.** git repo, Docker (Python 3.12), CI (build → ruff → pytest → demo smoke),
  ADRs 0001–0004, this backlog. See ADR 0003, 0004.

- ✅ **M3 — Calibration ledger (monetization keystone).** `anvil/ledger/` records every
  probabilistic forecast (±1σ / ±0.5σ bands, P(close>spot)) and scores resolved ones (Brier,
  log-loss, ECE, reliability curve, band coverage). CLI `anvil ledger record|resolve|seed|report`
  + API `/ledger/*`. Idempotent, immutable. See ADR 0004.
- ✅ **M4 — Live data + auth.** `anvil/auth/` (token store w/ 03:30 IST expiry, Upstox OAuth dialog
  + loopback capture + token exchange, Kite request_token→checksum→access_token); Groww connector
  (`growwapi`, lazy) + **gated, dry-run-default** `GrowwOrderGateway`; CLI `anvil auth …` / `anvil
  order … [--live]`. Multi-index lot/step config (NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NN50/SENSEX/BANKEX).
- ✅ **M5 — Consumer surface + grounded agent.** `anvil/agent/` deterministic narrator (every number
  from the engine) + optional Claude Q&A behind a **compliance guardrail** (blocks buy/sell/target/
  guarantee). Web UI at `/` (regime cockpit + market-implied distribution + reliability curve).
- ✅ **M2 — Storage rigor.** Deterministic idempotent snapshot IDs, cleaned `chain_rows` time-series
  (the moat), append-only ingest audit, Parquet export — `anvil/store/timeseries.py`.

## Now — Product Rewrap (active plan)

The active plan is the **Product Rewrap** (see `.claude/plans/upgrade-plan-stabilize-the-frolicking-walrus.md`):
turn the proven engine into a trust-first, live, multi-device PWA, all features unlocked (no tiers).
Sequenced into independently-executable milestones:

- ✅ **M0 — Stabilize foundation.** Repo-wide lint gate green (`ruff check .`); scratch `data/`
  (incl. the ad-hoc `fetch_real.py`) + vendored `reference/` excluded; clean baseline committed.
- ✅ **M1 — App/OLTP spine.** `anvil/db/` async SQLAlchemy + Alembic, 11 multi-user-ready tables;
  API restructured under `/api/*` + TTL cache.
- ✅ **M2 — Auth.** argon2id, server-side session cookies, owner bootstrap, account/profile/
  watchlists, per-user **encrypted** broker tokens (Fernet).
- ✅ **M3 — Provenance + live path.** Every payload stamped (live/backtest/demo/derived); Upstox
  live-ready across six indices; one-command broker-Greeks capture activates the validation gate.
- ✅ **M4 — Containerize + deploy.** Multi-stage Docker (node→python, image builds + boots),
  compose (app + Postgres + Caddy auto-TLS), `docs/DEPLOY.md` (Oracle Always Free / Render).
- ✅ **M5 — React/Vite PWA.** Question-organized dashboard, Simple/Trader/Expert modes, onboarding,
  visual language (range cone, OI walls, calibration diagonal, scenario heatmap, MC histogram),
  copilot + alerts UI; served same-origin by FastAPI.
- ✅ **M6 — Daily brief + what-changed + human calibration + grounded copilot** (model fixed to
  `claude-opus-4-8`); daily cycle writes snapshots + forecasts.
- ✅ **M7 — Alerts.** Grounded natural-language alerts + traffic-light severity; rule CRUD + evaluate.
- ✅ **M8 — High-value analytics.** Scenario grid, Monte Carlo P&L, event/expiry risk, IV-crush,
  unusual activity, participant-OI narrative, behavioral journal.
- ✅ **M9 — Hardening.** Structured JSON logging + request ids, DB-aware `/health`, `docs/SECURITY.md`,
  backups + launch-gate checklist.

**Remaining before paid launch (gates, not build):** activate the broker-Greeks fixture with real
Upstox keys; confirm market-data redistribution rights; SEBI counsel before accuracy marketing.
Deferred infra at scale: TimescaleDB + Redis (seams in place).
