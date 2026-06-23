# Claude Code prompt — Anvil: harden the moat, then ship the honest money layer

> Paste the block below into Claude Code running at the repo root (the folder containing `anvil/` and `realtime_sim/`).

---

You are working in the **Anvil** repo (`anvil/`) and its sibling package `realtime_sim/` (a live
Upstox prediction sim). First read `anvil/revamp/Anvil_Master_Build_Plan_v3.md` (the authoritative
plan — note the new **Appendix P4.A**) and `anvil/revamp/Anvil_Research_Report.md`. Then work the
Work Packages **in order**. This is a gate-bound project: **do NOT build WP4/WP5 until Gate-0 (WP3)
passes.** Report back after WP-SEC + WP0 + WP1 before doing anything irreversible.

## Non-negotiable guardrails
- **Read-only market data. NEVER place an order, move money, or wire live execution.** Keep
  `TRADING_AUTOMATION=false`; the execution layer stays gated/dry-run.
- **No guaranteed-returns and no "high-accuracy" (70–90%) claims.** The honest headline is
  *calibration* + *conditional accuracy at disclosed coverage*, never an unconditional hit-rate.
- "**Maximum monetization**" = maximizing the *user's own* trading returns via prediction quality.
  The app stays **free** — no paywalls/subscriptions. Don't add a revenue layer.
- Analytics/education framing only; in India paid securities advice can require SEBI Research-Analyst
  registration, so public surfaces must not emit buy/sell/target/sized language (that lives behind
  the PERSONAL_MODE wall in WP4).
- **Don't change the statistical formulas** (PSR/DSR/CSCV-PBO/Harvey-t are individually correct) —
  fix the *inputs* they're fed. Don't rewrite the engine. Don't add deep nets (they don't beat the
  baselines after costs at these horizons). Surgical changes only.

## Ground truth (measured 2026-06-22, NSE open; treat as given, don't re-derive wrong)
- **v1 directional model** (`realtime_sim/{model,tips,backtest}.py`): walk-forward ~8,800 decisions
  → **49.2% hit-rate, negative expectancy after costs**; raw confidence says 60–65% but delivers
  ~49% (overconfident, Brier 0.27). **No directional edge.** Keep ONLY as an abstention/baseline
  demonstrator; do not present it as tradeable.
- **v2 VRP option-structure model** (`realtime_sim/*_v2.py`): the real, non-circular VRP prior
  (sell the India-VIX-priced 1-day ATM NIFTY straddle vs realized next-day move, 492 trading days)
  = **≈+16%/yr, Sharpe 1.89, win-rate 65%**, BUT short-vol fat tail (**maxDD −13.7%, worst-day
  −2.8%, CVaR5% −₹14.5k**); realized/implied ≈ **0.84** (premium structurally rich). Live tip sheet
  is **0 ACTIONABLE / heavy ABSTAIN** (correct for a fresh, unproven book). **This is the credible
  edge — build on it, but gate-bound.** It is a *prior on a clean proxy*, NOT a certified live track
  record, and it sells insurance.
- Any current `edge-verified ✓` in the ledger is **suspect** until WP0 lands (the gate currently
  doesn't count trials, day-block, or purge).
- Upstox is connected via an **extended token valid to 2027** (read-only market data works; a
  browser User-Agent is required because Cloudflare 403s the default agent).

## WP-SEC — secrets (do immediately, 5 min)
1. Verify `anvil/.env.example` holds **placeholders only** (no real keys) and `anvil/.env` is
   gitignored. Delete `anvil/.env.example.bak` if it exists.
2. Print a clear reminder that the **user must rotate the Upstox API secret and Groww credentials**
   on the provider side (they were previously committed). You cannot do this for them.

## WP0 — Harden the gate (Plan Phase 0; blocks trust in everything) — DO FIRST
1. Add a persisted **experiment/trial registry** (DuckDB table) that monotonically counts every
   config/threshold/target sweep evaluated against the dataset. In `backtest/aggregate.validate_cells`
   set `n_trials = max(len(cells), trials_logged)` and feed PBO the tried-config matrix, not just
   survivors.
2. Route `tip_backtest.py`, `equities.run_equity_backtest`, and `IssuedTipStore.resolved_cells`
   through `cell_from_daily` so significance uses **independent-day** counts (effective-n = days),
   exactly as the touch path already does.
3. Wire **CPCV** (`combinatorial_purged_splits` / `purged_walk_forward_splits`) into certification
   with `embargo ≥ label horizon`.
4. Tidy deflation: stop pooling cross-family Sharpes for `sr_variance`; fix the single-cell
   optimistic-variance floor; add a freshness/model-version check to `gate.decide_tier`.
- **Acceptance:** a regression test plants a deliberately overfit cell + sweeps a threshold and the
  gate's bar **rises and rejects it**; re-running the Sep–Nov cells yields **fewer green** than before;
  full suite stays green.

## WP1 — Data unlock + always-on recorder (run in PARALLEL with WP0; time-urgent)
1. Stand up the always-on intraday **chain recorder** (`recorder.TickRecorder` + `store.SnapshotStore`)
   on a scheduler — that OI/IV history is unbuyable and lost daily.
2. Harden + run the **24-month NSE bhavcopy backfill** (resume-from-cache, retry/backoff, polite
   parallelism; exercise the pre-2024 legacy schema).
3. Backfill closes for **NIFTY + BANKNIFTY + INDIA VIX** (Yahoo `^NSEI`/`^NSEBANK`/`^INDIAVIX`).
4. Decide **SENSEX**: build a BSE bhavcopy ingestor or mark it live-only/uncertifiable. BankNifty is
   monthly-expiry only (weeklies discontinued Nov-2024) — key cells on monthly expiries.
- **Acceptance:** ≥24 months cached + reconciled; recorder running on schedule; a written SENSEX decision.

## WP2 — Calibration layer (the missing heart)
1. Pure-numpy **PAV isotonic + Platt fallback** mapping each target's raw score → calibrated prob,
   fit on resolved `struct_live` history, refit on a cadence.
2. **Per-target** calibration, then decorrelated combination (whiten shared `atm_iv`/`total_gex`
   before combining — no naive agreement count).
3. **Adaptive/temporal conformal** + a risk-calibrated **abstain threshold** replacing the hard-coded
   magic numbers (`decision_brief` 0.62/0.45, `iv_crush` 66).
- **Acceptance:** per-target reliability curves near-diagonal (out-of-fold ECE < 0.10); abstain
  threshold set from measured coverage, not constants.

## WP3 — Gate-0 re-certify (the kill switch) — MEANINGFUL, not on thin data
With WP0 (fixed gate) + WP1 (real multi-year data) + WP2 (calibration): walk-forward, per target,
**threshold chosen inside the loop and counted as a trial**. Pass bar (verbatim): *at least one
target sustains ≥ ~65% calibrated accuracy at ≥ ~10–15% coverage with DSR ≥ 0.95, PBO ≤ 0.5, Harvey
t ≥ 3, trials counted.* Report per-target accuracy–coverage curves.
- **Run it MEANINGFULLY** (only with WP0+WP1+WP2 in place); a Gate-0 on the current thin, single-
  regime Sep–Nov cache is statistically vacuous — expect FEWER/zero green cells and treat that as the
  gate working, not a failure. **Go/no-go:** pass → build WP4. Fail → accept lower accuracy at higher
  coverage, or abstain in that regime. **Do not build WP4/WP5 until Gate-0 passes.**

## WP4 — Honest money layer + PERSONAL_MODE wall (ONLY after Gate-0 passes)
1. Fix `strategy/sizing.size_units`: **edge-uncertainty shrink** (shrink `edge_prob` toward 0.5 by
   its std-error/sample count), a **CVaR/tail cap** as a fourth binding term, size on **cost-adjusted**
   EV, a **broker-margin feasibility cap**; unify the two `SizingConfig`s; make naked `max_loss` a
   **CVaR-based true tail**, not the stop multiple.
2. Attach the **distribution to every ticket** (`engine.montecarlo.mc_pnl`: EV percentiles, VaR/CVaR,
   risk-of-ruin, forward-drawdown) — never a point-₹ hero number.
3. Build the **`PERSONAL_MODE` hard wall** (`ANVIL_PERSONAL_MODE`): sized/actionable buy/sell/target
   language emitted ONLY behind owner-only auth; public default = analytics (`Prediction` without
   `actionable_tip`); `check_compliance` stays the default block. Document as ADR 0006.

## WP-V2 — Consolidate the VRP sim (the build-on; aligns with Appendix P4.A)
The `realtime_sim/*_v2` family (engine_v2/structures_v2/sizing_v2/costs_v2/gate_rank_v2/tracker_v2/
live_v2/backtest_v2/serve_v2) is a faithful, honest, pure-stdlib VRP-structure layer and is the right
foundation. Do:
1. **Make it durable & correct:** ensure `config.py` keeps the single canonical `V2_*` block (no
   duplicates), and `upstox_client.py` keeps `option_chain_by_key` + `_lot_size_from_contract`
   (these were lost twice to a filesystem write issue — see WP-DUR). Verify `python live_v2.py` and
   `python backtest_v2.py` both run.
2. **Accrue the forward track record:** schedule `python resolve.py`-equivalent for v2
   (`tracker_v2.resolve_open`) daily after close so `tips_v2.db` cells gain resolved samples; keep
   the mandatory tail stats (maxDD/CVaR/Calmar) visible; ACTIONABLE only after a cell clears the
   WP0/WP3 gate (n≥50, post-cost edge>0, DSR/PBO/t bars).
3. **Feed the moat:** route v2 structure outcomes into the same calibration ledger + gate as WP0/WP2
   so the VRP cells are certified by the *same* battery (no parallel, weaker gate).
4. Treat the +16%/yr VRP backtest as a **prior**, label it as such in any UI, and never let it
   short-circuit Gate-0.

## WP-DUR — durability (do early)
`realtime_sim/` is a sibling of `anvil/` and is NOT under the anvil git repo; its files have been
intermittently truncated/null-padded/reverted by the filesystem. Put `realtime_sim/` under version
control (add to the repo or its own git), commit the known-good v2 + config + client, and add a tiny
`python -m py_compile *.py` pre-commit/CI check so any corruption is caught and recoverable.

## What NOT to do
- Don't revamp the engine, add deep nets, or trust any `edge-verified ✓` before WP0.
- Don't make the monetization/identity memory edits sticky until Gate-0 passes.
- Don't ship sized/actionable language on any public surface (PERSONAL_MODE wall only).

## First actions
Do **WP-SEC + WP-DUR + WP0**, run WP1 in parallel, then STOP and report calibration/gate results
before WP2→WP3. Keep every change behind tests; keep abstention first-class.
