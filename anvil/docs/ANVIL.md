# Anvil — Canonical Documentation (complete context)

> **What this file is.** The single living reference for Anvil: what it is, how it's built, the
> **history of changes (past → current state)**, and the **planned future**. It is the place a new
> reader (or a future session) gets full context.
>
> **How it differs from the trackers.** [`next_wave.md`](../../next_wave.md) (top-priority "what to
> build next") and [`future_waves_of_upgrade.md`](../../future_waves_of_upgrade.md) (the ordered
> backlog + cited research) are **task lists**. This file is the **narrative + architecture + state
> record**: why things are the way they are and what shipped when.
>
> **Maintenance rule (standing).** Whenever a wave or substantive change lands, update this file:
> append to the **Change history**, refresh **Current state**, and adjust **Future waves**. Keep it
> truthful — record what actually shipped, including what is honest-but-dormant.
>
> _Last updated: after **Wave I — Innovation Engine revamp** (orthogonal momentum/dealer-flow/chain-dynamics/constituents engines + factors; meta-label + decorrelated ensemble + orthogonality admission gate; full data layer + multi-timeframe momentum end-to-end; one-process `anvil go-live` cockpit). Tests: full suite green (excl. slow tip_backtest) / 1 skipped, ruff clean. New fusion layer built+tested but not yet wired into the live predict path (awaits resolved-history training)._

---

## 1. What Anvil is

A **personal, calibration-first options-intelligence PWA** for Indian markets (NSE/BSE), React+Vite
over FastAPI. The thesis (see [`PITCH.md`](PITCH.md), [`hypothesis.md`](hypothesis.md), ADR
[`0004`](decisions/0004-calibration-first-compliance.md)):

- **Calibrated, and "accurate" — when it speaks.** It sells what you can audit: probabilistic reads
  each shown on a **live, public reliability curve**. The accuracy target is honest and *conditional* —
  **~62–68% (stretch 70–80%) on the ~10–20% of opportunities the engine is confident enough to call**,
  not an unconditional headline; on the rest it **abstains**. The North-Star goal is **operator P&L**,
  earned by sizing the few high-conviction calls well. (How this is substantiated:
  [`METHODOLOGY.md`](METHODOLOGY.md); the personal/public wall that keeps it compliant: ADR
  [`0006`](decisions/0006-personal-mode-hard-wall.md).)
- **Honest by construction.** Nothing claims edge it hasn't measured. Where evidence is thin the
  product **abstains / shows "tracking"** rather than fabricates. Synthetic/demo/paper data is
  firewalled out of every public curve by a source-class rail.
- **Paper + analytics only.** No real order execution; no investment advice; no monetization
  (flat-free, all features). Greeks are **Black-76 on the futures price** (ADR
  [`0002`](decisions/0002-greeks-black76-on-futures.md)), never BSM on spot.

### Non-goals (standing)
No billing/tiers/paywalls. No automated execution. No fabricated accuracy. No daily-direction oracle
(see Wave-2 re-aim below).

---

## 2. Architecture map

Backend package `anvil/anvil/` (engine-tier = pure functions over numpy + DuckDB; **pandas-free**):

| Area | Path | Role |
|---|---|---|
| **engine/** | `anvil/engine/` | Quant primitives: `greeks` (Black-76), `implied_dist` (Breeden-Litzenberger RND), `gex`, `vol`, `regime`, `iv_crush`, `event_risk`, `oi`, `montecarlo`, `scenarios`, `participant_oi`. **Wave 2 added:** `touch_probability`, `realized_vol_forecast`, `term_structure`, `regime_score`, `decision_brief`. |
| **strategy/** | `anvil/strategy/` | `SignalContext` (the analytics surface), `TradeCandidate`/`Leg`, `generate` (candidate gen + conviction; `safe_sizing` honest path), `library`, `sizing` (fractional Kelly + **P4 edge-shrink / CVaR / margin / short-vol caps**), `tail` (naked stress / vol-scaled true tail). |
| **factors/** | `anvil/factors/` | Composable regime-gated alpha factors (`@register`): `index_options`, `equities`, `events`, `regime_gate`. |
| **tips/** | `anvil/tips/` | The tip/prediction surface: `types` (`Tip`, `Prediction` + owner/public serialization), `build`, `pipeline`, `predict`, `risk` (**P4 mc_pnl risk map + ruin/drawdown**), `gate`, `calibration`, `resolve` (`terminal_payoff`, `resolve_outcome_from_path`), `store` (`TipValidationStore`/`IssuedTipStore`), `eod`, `intraday`, `equities`. |
| **backtest/** | `anvil/backtest/` | The anti-overfit moat: `validation` (CPCV/embargo, Deflated-Sharpe, PBO, Harvey t≥3), `aggregate` (`validate_cells`, `cell_from_daily`), `data` (`BhavcopyArchive`), `asof` (`AsOfContext` look-ahead guard), `tip_backtest`, `revalidate`, `robustness`, **`gate0`/`gate_report` (Phase 3), `vrp_prior` (Phase-5 VRP edge prior)**. |
| **ledger/** | `anvil/ledger/` | `CalibrationLedger` (DuckDB forecasts+outcomes), `scoring` (Brier/ECE/reliability), source-class firewall, forecast kinds + `emit_*`. |
| **ingest/** | `anvil/ingest/` | Data connectors: `upstox`/`groww`/`dhan`/`kite` (live), `bhavcopy`/`nse_eod` (EOD), `demo`, `events`. **Wave 2 added:** `yahoo` (pandas-free chart-JSON OHLC + India VIX). Token-aware `source.pick_connector`. |
| **live/** | `anvil/live/` | Realtime loop (`live_runner` + Phase-5 opportunistic resolution/coverage, `eventbus` incl. `TIP_RESOLVED`/`TRUST_DIAL`, `recorder`, `clock`), `closes` (Phase-5 realized-close ladder), nightly `cycle`/`daily` (auto-resolve moat clock). |
| **paper/** | `anvil/paper/` | Paper-trading subsystem (costs, margin, governor, mtm, report) — the "make money" mock loop. |
| **api/** | `anvil/api/routers/` | FastAPI routers incl. `tips`, **`decision_brief`** (Wave 2), `copilot`, `brief`, `portfolio`, `paper`, `alerts`, `ledger`, `auth`. |
| **agent/** | `anvil/agent/` | Grounded LLM `analyst` + compliance `guardrail` (`check_compliance`). |
| **gating.py** | `anvil/gating.py` | **P4 emission interlock** (ADR 0006): `gate0_passed` / `personal_mode_armed` — the runtime gate on actionable/sized output. |
| **web/** | `anvil/web/src/` | React PWA: `App.tsx` (tabs: Today / Tips / Simulator / Risk / Copilot / Alerts / More), `charts.tsx`, `api.ts`. |
| **cli.py** | `anvil/cli.py` | `anvil pull|serve|ledger|backtest|tips|paper|auth|order|data|decision-brief`. |

The **moat** is the validation harness + the calibration ledger + the source-class firewall: any new
engine/signal must clear the *same* gate (sample size, calibrated win-rate, Harvey t≥3, Deflated
Sharpe ≥0.95, PBO ≤0.5, robust bootstrap) before it may headline, and lives on its own ledger class.

---

## 3. Data sources (reality)

- **Live option chains + Greeks/IV:** Upstox (primary), Groww/Dhan (fallback), Kite (positions only).
  Token-aware resolver picks live vs demo; provenance stamped on every payload.
- **EOD options history:** NSE F&O **bhavcopy** (free, cached in `data/bhavcopy_cache/`). Includes
  single-stock `STO`/`STF` + `UndrlygPric` (cash close) + `NewBrdLotQty` (lot). ~3 months cached;
  multi-year fetch is best-effort and deferred to the validation wave.
- **Daily OHLC + India VIX (Wave 2):** Yahoo chart JSON (`^NSEI`, `^NSEBANK`, `^INDIAVIX`, `{SYM}.NS`),
  pandas-free, cached in `data/closes_cache/`, IST-trading-date keyed. Gives RV/VRP/regime history
  **and** the daily high/low for honest touch resolution.
- **Events:** committed RBI/Budget/expiry seed (`ingest/events.py`) + optional `data/events.csv`.
- **Not yet ingested:** multi-year bhavcopy, BSE bhavcopy (SENSEX), FII/DII + participant-OI history,
  earnings calendar at scale, news/sentiment. (See Future waves.)
- **Dependency reality (Python 3.14 venv):** numpy/scipy/duckdb/httpx present; **no** pandas /
  scikit-learn / arch / hmmlearn (no cp314 wheels) → realized-vol (HAR-RV/EWMA), regime (rules), and
  touch (MC) are all **pure-numpy**. LightGBM ships a `py3-none` wheel (reserved for the ML wave).

---

## 4. Change history (past → current state)

### Baseline (pre-Wave-1)
Calibration ledger + reliability curves; Black-76 engine (RND, GEX, IV-rank, regime, IV-crush, event
risk); strategy/candidate engine; paper-trading subsystem; the validation harness (CPCV/DSR/PBO/t≥3);
React PWA dashboard (Today/Simulator/Risk/Copilot/Alerts). The TIPS engine's *plumbing* shipped
(M0–M4) but was **inert** — never run, so the headline feed was always empty.

### Wave 1 — Live predictions, single-stock tips, rich UI, live wiring
Fixed "the product ships dark":
- **Never-empty prediction layer** (`tips/predict.py`, `Prediction`): always surfaces the engine's
  best read + a calibrated confidence; an **"Edge-verified ✓"** badge earned only via the gate.
- **Single-stock BUY/SELL tips** (`factors/equities.py`, `tips/equities.py`): cross-sectional
  momentum on free bhavcopy STO/STF; EQ-leg tips through the same Tip→ledger→validation spine.
- **Ran the validation backtests** → populated real `tip_validation` cells (21 index + 38 equity +
  pooled). All honestly `headline_eligible=False` on ~3 months (e.g. `short_strangle` 86.8% win-rate,
  n=38, but doesn't clear DSR — the moat working).
- **Cash-close resolution, nightly re-validation** (`backtest/revalidate.py`), **live-mode tip pass**
  (`run_live` + `PREDICTION` event), **gated event-calendar factor**, **rich Tips tab**
  (PredictionCard, FactorBars, PayoffDiagram, RiskCoverageCurve, equity BUY/SELL).
- Result: 284 tests green; the Tips tab is substantive in demo and live.

### Wave 2 — Buyer Decision-Brief engine (re-aimed after a red-team)
A red-team ([`Anvil wave2 challenge`](Anvil%20wave2%20challenge)) rejected a planned **ML
daily-direction** engine: wrong target (least achievable/useful/safe for a buyer), and another dark
engine before the data. Accepted re-aim → **predict the buyer's real questions, surface them now**:
- **`engine/touch_probability.py`** — P(spot touches strike K within horizon T): GBM Monte-Carlo at
  implied vol with a **Brownian-bridge discrete-monitoring correction (C1)**, a **VRP-adjusted
  physical** read using the **live `forecast_RV/ATM_IV` (C2)**, one **shared path ensemble (C13)**.
- **`engine/realized_vol_forecast.py`** — **Garman-Klass RV (C4)** + HAR-RV/EWMA forecast; VRP
  recorded as a **resolvable probability** `P(realized<implied)` **(C7)**, **horizon-matched (C5)**.
- **`engine/term_structure.py`** — front/next IV slope → contango/**backwardation** (event imminent);
  expected move ≈ 0.85×ATM straddle; crush-abstention window.
- **`engine/regime_score.py`** — trend/range/squeeze as an **agreement count (C9, never an accuracy %)**.
- **`engine/decision_brief.py`** — composes **environment-gate → strike-action**: a verdict
  FAVORABLE/NEUTRAL/UNFAVORABLE/**ABSTAIN** (abstention is the default) with a **`flip_condition`
  (C10)**, then the VRP-adjusted P(touch) strike table (muted when unfavorable).
- **Ledger:** `KIND_PROB_TOUCH` (resolved from realized daily high/low) + `KIND_VRP_RICH`, a
  `STRUCTURAL_CLASSES` firewall, `emit_structural_forecasts`, and **day-blocked significance
  (`aggregate.cell_from_daily`, C3)** so correlated same-day touch labels can't inflate the gate.
- **Data:** `ingest/yahoo.py` (C6 IST date discipline). **API:** `/api/decision-brief/{u}`. **CLI:**
  `anvil data fetch-closes`, `anvil decision-brief [--record]`. **UI:** a **plain `DecisionBriefCard`
  table first (C11)** at the top of the Tips tab; bespoke charts deferred.
- Result: all C1–C14 corrections folded in and tested; 300+ tests green; the server serves it live.

### Wave 3 / Phase 2 — Calibration layer (the missing heart of "calibration-first")
The product *measured* calibration (ECE, reliability) but never *performed* it. Added `anvil/calibration/`:
- **`isotonic.py`** — pure-numpy **PAV isotonic** + scipy **Platt** fallback + **identity** degradation;
  `fit_calibrator` returns identity below `min_samples` and **λ-blends toward identity** in the mid-n
  band, so a map **glides up** as live data accrues (never overfits the near-empty live store).
- **`crossval.py`** — every quality number (ECE before/after) is **OUT-OF-FOLD** via the Phase-0
  purged walk-forward splits; in-sample ECE is never trusted.
- **`conformal.py`** — `risk_coverage_threshold` picks the abstain `tau*` (max `coverage·edge` over a
  breakeven floor) on TRAIN folds, reports on TEST, logs the tau-grid to the `TrialRegistry`; **Mondrian**
  (regime-conditioned) thresholds; **ACI** interface (default off until live streams).
- **`combine.py`** — Ledoit–Wolf-shrunk **ZCA whitening** of the shared `atm_iv/total_gex/vrp_ratio`
  (no-op below min-n) so a combination never **agreement-counts** one vol shock; LogisticStacker deferred.
- **`store.py`/`service.py`** — a `calibrators` DuckDB table PK `(target, source_class)` (**the firewall**)
  with **OOF** `ece_before/after`, `abstain_tau`, `lambda_blend`, `CALIBRATION_VERSION`; `CalibrationService`
  applies maps at predict time (identity-safe) and `fit_all_targets` fits per source-class on a cadence.
- **Wiring (display/threshold only — NOT the gate):** new `Tip.calibrated_edge_prob`/`Prediction.
  calibrated_confidence` display fields (sizing still runs off the RAW edge — P4 boundary; the gate's
  `win_rate≥conviction` check still tests the RAW conviction, so calibration can't make it pass by
  construction); de-magicked thresholds (`decision_brief` 0.62/0.45, `iv_crush` 66, equities cap,
  `predict` 0.54/0.46) are now config-backed and optionally calibrated, with raw fallbacks (byte-identical
  until live tips resolve); nightly refit in `live/cycle.run_daily_cycle`; calibrators surfaced on
  `/api/tips/track-record` + `/api/ledger/report`. **CLI:** `anvil calibrate fit|report`.
- Honest framing: calibration is the **honesty rail + sizing precondition**, NOT a tip-firing/P&L
  unlock. Only `conviction/tip_backtest` (n≈775) fits today; all other targets degrade to identity and
  strengthen via the nightly refit. The Sep–Nov 2025 map is **provisional** pending the multi-year
  backfill. 48 calibration tests added.

### Wave 3 / Phase 3 — Gate-0, the kill switch
With the hardened gate (P0) + calibration (P2), Gate-0 asks honestly, **per target**: does the
high-confidence bucket sustain usable **calibrated** accuracy at usable coverage, with the decision
threshold chosen INSIDE the walk-forward loop and **counted as a trial**? An ABSTAIN ("not enough
evidence yet") is a correct outcome — we never tune toward green.
- **Closed the last two P0 embargo holes:** OPTIONS (`tip_backtest`) and LIVE (`revalidate`) now thread
  `embargo = the label horizon` (issue→resolution span in independent trading days, via the new
  `backtest/horizon.py`) into the OOF edge checks, matching what EQUITY already did — a weekly/monthly
  option whose label spans >5 days can no longer leak train↔test (was: silent `embargo=5`).
- **CPCV is now EXERCISED, not just defined:** `cpcv_oof_edge_combinatorial` (median edge across the
  ≈C(6,2)=15 purged paths) is a second eligibility condition in `validate_cells`, alongside the
  walk-forward OOF edge — an edge must hold across a MAJORITY of held-out combinations, not just the
  forward folds. (Decision: wire it, don't defer.)
- **EV-at-coverage (the money knob):** `conformal.ev_coverage_threshold` is the train→test, trial-counted
  sibling of `risk_coverage_threshold`, optimizing realized `coverage · mean(net-of-cost return)`. The
  operating τ is set on EV × coverage (P&L), with accuracy-at-coverage reported alongside — accuracy isn't
  money.
- **The orchestrator + artifact:** `backtest/gate0.py` calibrates each target, runs the in-loop
  trial-counted threshold sweep (every grid bumps the `TrialRegistry` → the Deflated-Sharpe bar rises with
  search), measures OOF accuracy/EV at the operating point, and runs the full battery across the **grid of
  tried thresholds as PBO configs**. `backtest/gate_report.py` writes `gate0.{json,md,svg}` (dependency-free
  SVG accuracy-/EV-vs-coverage curves; JSON feeds the web charts). **CLI:** `anvil gate0`.
- **Data:** the 24-month NSE bhavcopy backfill **landed** — **624 trading days cached, 2023-12-01 →
  2026-06-19** (was 62), via the hardened resumable `data backfill` (now honors 429/503 `Retry-After` +
  writes a checkpoint log). The Phase-2 "provisional pending backfill" caveat is now resolvable on real
  depth. *Caveat:* `BhavcopyArchive.from_cache_dir` loads the whole cache into memory, so a full-depth
  cert needs a **chunked/streaming archive loader** (follow-up); the provisional cert runs on a windowed
  subset.
- 16 Phase-3 tests added (combinatorial CPCV, embargo=horizon on both engines, EV-at-coverage, the
  trial-counted sweep raising the bar + rejecting a planted overfit, the report artifact, backfill 429/
  resume). Full suite green.
- **Provisional 62-day verdict (Sep–Nov 2025): NO-GO / ABSTAIN — and informatively so.** `conviction`
  abstains on a SINGLE constraint: **Harvey t = 2.64 < 3.0** (n=212 trades → only **12 independent days**;
  t = SR·√n). Everything else clears: calibrated (isotonic deployed), **DSR 0.975, PBO 0.37, accuracy 74.8%,
  coverage 85.8%, EV +0.38**. The edge looks real but lacks independent-day evidence — full depth (624 days
  → ~120+ independent days) scales t ≈ 3.2× and would clear the hurdle if it holds. `equity` abstains
  correctly (negative-EV after costs). This is honest discovery working as designed. **Do NOT build P4
  (sizing) / P5 (live loop) until Gate-0 PASSES on full depth** (which first needs the chunked archive loader).

### Wave 3 / Phase 4 — Honest money layer + the personal-mode hard wall
Phase 4 builds the SIZING SAFETY, the per-ticket RISK DISTRIBUTION, and the owner-only WALL — but keeps
actionable EMISSION gated on Gate-0 (the machinery lands now; sized personal tips stay dark until the
conviction cell clears). Decision: *build safety+wall now, gate emission* — honoring "don't build P4/P5
until Gate-0 passes" as a RUNTIME invariant rather than a reason to wait.
- **Honest sizing (`strategy/sizing.size_units`).** One `SizingConfig.from_settings()` factory (the two
  former construction sites — `generate.py`, `tips/equities.py` — unified), plus four safeguards, each OFF
  unless its per-call input is supplied (so the gate/backtest path stays byte-identical and certified
  cells, which use units-independent return-on-risk, are unaffected): **edge-uncertainty shrink** (Kelly
  edge haircut by z·SE, MEASURED cells only — unmeasured skepticism stays the gate's job, so the engine
  isn't silenced on a thin book), a **CVaR/tail cap**, a **broker-margin feasibility cap** (the sized
  number is always placeable; agrees with the governor), and the **short-vol Kelly hard cap (0.10)** —
  the negative-skew guard ported from the v2 sim. Naked structures carry a **stress (≈3σ) tail**
  (`strategy/tail.py`) fed to the CVaR cap so we size against the gap, not the modeled stop (`max_loss`
  stays the EV/stop number — replacing it would corrupt EV). Activated on the LIVE tip/prediction path
  (`safe_sizing=True`); OFF in the backtest.
- **Distribution on every ticket (`tips/risk.py`).** The actionable tip carries an **mc_pnl risk map**
  (percentiles + VaR/CVaR — risk-neutral, a risk map NOT a return forecast) plus **risk-of-ruin +
  forward-drawdown** from a repeated-bet Monte-Carlo (`legs_to_positions` → `mc_pnl`; `ruin_and_drawdown`
  over modeled return-on-equity). Shown instead of a point-₹ number. OWNER-only.
- **The hard wall (ADR [0006](decisions/0006-personal-mode-hard-wall.md)).** `ANVIL_PERSONAL_MODE`
  (default OFF → public analytics). `Prediction.to_dict(owner=…)` / `public_dict()` is the enforced
  boundary: the public surface emits the calibrated read with NO actionable tip, sized legs, or risk
  distribution. `auth/deps.require_personal_owner` is the single owner gate; the actionable feed is a
  sibling route `GET /api/tips/{u}/actionable`. **Double-gated:** `gating.personal_mode_armed()` =
  personal mode AND `gate0_passed()` (≥1 cell headline-eligible at Harvey t ≥ 3) — so even the owner gets
  analytics-only until the edge certifies. The live-runner SSE egress applies the same gate (ledger
  recording stays full — that's internal measurement, not egress).
- New tests: `test_sizing_phase4`, `test_tip_risk`, `test_personal_wall` (no-op equivalence, each
  safeguard binds, the serializer invariant, the Gate-0 interlock, the owner-gate logic, public carries
  no actionable). Full suite green.
- **Still gated:** sized personal tips do not surface until Gate-0 passes on full depth. The v2-port
  decision is *port fully, then retire `realtime_sim`*; the short-vol Kelly cap, naked stress tail, and
  distribution/tail-stats deltas are now in anvil's canonical modules — the remaining ports (governor
  portfolio short-vol stress cap, modeled-stop naked resolution, the non-circular VRP-prior backtest +
  `tips_v2.db` migration) and the `realtime_sim` deletion are staged follow-ups pending live-parity.

### Wave 3 / Phase 5 — Live sized tips loop: the accrual + trust-dial machinery
Phase 5 builds the loop that *earns and shows* trust continuously so that, when the gate certifies,
calibrated, gated, honestly-sized tickets flow end-to-end. Same framing as Phase 4: **build the
accrual/trust machinery now; emission stays walled and auto-arms on certification.**
- **Automatic resolution (the keystone).** Resolution was MANUAL — `run_daily_cycle`/`run_tip_cycle`
  only resolved tips for underlyings the operator hand-fed a `realized={u: close}` dict, so the live
  track record never accrued on its own. New `live/closes.py:realized_closes_for` answers "what did it
  settle at?" causally — a strict ladder (BhavcopyArchive → Yahoo cache → after-close spot proxy),
  omitting (never guessing) what isn't published, never VIX. Wired as an opt-in `auto_resolve` flag
  (default OFF → backtest/tests byte-identical) that the moat clock (`anvil ledger run-daily --full`)
  and the live loop turn ON. `tips/resolve.settle_with_modeled_stop` ports the v2 honest resolution
  (naked books the WORSE of stop and settlement; `path=None` degrades to exact `terminal_payoff`).
- **Continuous live accrual.** `run_live` opportunistically resolves same-day-due tips against a
  PUBLISHED close (spot fallback OFF → causal) and publishes a wall-gated `TIP_RESOLVED` SSE event.
- **Coverage logging.** New `tip_coverage` table + `IssuedTipStore.bump_coverage`/`coverage_rolling`:
  how often the engine SPEAKS (actionable) vs abstains — additive on the live tick path, REPLACE on the
  EOD path (idempotent). The honest denominator behind "size the few good calls well, not call volume."
- **The live trust dial.** `tips/trust_dial.build_trust_dial` + `GET /api/tips/trust-dial` compose the
  reliability curve (`metrics_for_tips`) + accuracy-at-coverage operating point + coverage % + the v2
  tail-stats scorecard (maxDD/worst/CVaR5%/Calmar/Sortino over resolved tips — win-rate never alone) +
  per-cell verdicts + the **VRP-prior anchor** (`backtest/vrp_prior.py`, labeled "prior, not a track
  record") + the gate/armed status. A compact `TRUST_DIAL` SSE event streams the live snapshot.
- **Armed-ticket completeness.** `Prediction.roe_overlay` (owner-only) surfaces the win/loss
  return-on-equity + breakeven the ruin MC already computes.
- **v2 port (toward retirement).** Ported: the VRP-prior backtest, the portfolio short-vol stress cap
  (`paper/governor.cap_short_vol_exposure`), the modeled-stop resolution, the tail-stats scorecard. A
  one-shot `scripts/migrate_tips_v2.py` folds `tips_v2.db` into the ledger with reconciliation —
  **migrate → revalidate → REVIEW the gate0 report/trust-dial before trusting any newly-armed
  emission**, then delete `realtime_sim/`. New tests: `test_auto_resolution`, `test_modeled_stop`,
  `test_coverage_logging`, `test_trust_dial`, `test_vrp_prior`, `test_portfolio_cap`.
- **Scheduling (moat clock).** `anvil ledger run-daily --full` (no `--realized`) is the self-contained
  moat clock (auto-resolve + accrue + revalidate + refit). Schedule it via **Windows Task Scheduler**
  ~16:05 IST (after `anvil data fetch-closes` refreshes the caches): `schtasks /Create /TN "Anvil Moat
  Clock" /SC DAILY /ST 16:05 /TR "<venv>\python.exe -m anvil.cli ledger run-daily --full --underlying
  NIFTY,BANKNIFTY"`. Run the always-on recorder (`anvil record run`) as its own task. (An in-process
  FastAPI-lifespan scheduler behind `ANVIL_MOAT_CLOCK` is designed but kept OFF — a future opt-in.)
- **Still gated:** sized personal tips do not surface until a validation cell is headline-eligible at
  Harvey t≥3 — the interlock enforces it at runtime; Phase 5 makes the loop accrue the evidence and
  show the dial so that pass can happen and is delivered the moment it does.

### Wave 3 / Phase 6 — Docs / ADRs / identity (the honest-framing pass)
The last phase of the master plan: make the *documentation and product identity* tell the same honest
story the code already enforces. **No engine/gate/sizing/calibration change** — display + docs only.
- **§1 self-contradiction fixed.** The old §1 line that named an unconditional **70–80% directional
  accuracy** as the headline goal (which contradicted [`hypothesis.md`](hypothesis.md)) is replaced by
  the **conditional** framing:
  ~62–68% (stretch 70–80%) on the ~10–20% of opportunities the engine is confident enough to call, on
  the live reliability curve; the goal is **operator P&L**. The "high accuracy" brand is *kept and
  substantiated*, not dropped and not re-litigated; "No fabricated accuracy" stays.
- **`METHODOLOGY.md` (new)** — the canonical "how Anvil earns the word 'accurate'" disclosure:
  accurate-when-it-speaks, measured-not-asserted (the gate battery + source firewall), the money
  discipline (tail shown, win-rate never alone), the two-surfaces wall, and the SEBI analytics/
  education lane (with the one-time "securities lawyer before accuracy copy ships" flag).
- **ADR [0005](decisions/0005-bsm-on-spot-deferred.md) (new — deferral)** records that BSM-on-spot is
  *not built and not needed*: index options are Black-76 on the forward (ADR 0002), single-stock tips
  are cash `EQ` legs only (no option structures), so no spot pricer exists. Closes the live ADR tree's
  0004→0006 numbering gap and documents the trigger to revisit. ADR
  [0006](decisions/0006-personal-mode-hard-wall.md) (the personal-mode wall, written in Phase 4) was
  verified against `gating.py` and cross-linked.
- **In-product Trust / Methodology panel (new)** — a read-only section at the top of the **More** tab
  composing the EXISTING `/api/calibration` + `/api/tips/trust-dial` endpoints (reliability curve,
  accuracy-at-coverage, coverage %, the tail scorecard, the VRP prior, and the honest **gate state —
  sized tips shown as DARK until Gate-0 certifies**). Display-only; reuses `charts.tsx`; no new engine.
- **Docs-honesty lint (`tests/test_docs_honesty.py`, new)** — fails the build if the unconditional
  accuracy-as-headline-goal claim resurfaces, if a doc asserts a current spot-BSM capability, or if the
  ADR set grows a gap. The honest framing is now *enforced, not asserted in prose*.

### Wave I — Innovation Engine revamp (orthogonal multi-disciplinary edge + one running cockpit)
Post-Phase-6 revamp aimed at the operator goal: raise selective accuracy by fusing *genuinely
orthogonal* signals (quant / microstructure / behavioural / info-theory), run the whole thing as ONE
live process, and add the long-requested **multi-timeframe momentum**. Honesty rails unchanged
(gate/sizing/calibration untouched; new signals are display-only until certified).
- **New orthogonal signal engines (pure-numpy):** `engine/momentum.py` (multi-timeframe TSMOM +
  cross-sectional + intraday OR/VWAP/gap + Baltussen last-30-min), `engine/flow_momentum.py` (OI/GEX/
  IV-rank/term velocity over recorded history), `engine/dealer_flow.py` (vanna/charm hedging exposure +
  gamma-flip S/R), `engine/chain_dynamics.py` (fitted IV-skew slope, OI-change bias, smart-money volume
  blocks, 0DTE pin, max-pain drift), `engine/constituents.py` (BankNifty ~5≈82% → index breadth +
  stock→index lead-lag).
- **Factors (display-only — `_conviction` does not read them; the gate/ensemble decide tradeability):**
  `factors/momentum.py`, `factors/dealer_flow.py`, `factors/chain_analytics.py` — all abstain-safe, so
  the legacy chain-only path is byte-identical.
- **Anti-overfit / fusion layer (Innovation I.4, built + tested; not yet wired into predict — awaits
  resolved-history training):** `backtest/orthogonality.py` (MI/residual-info admission gate that
  REJECTS redundant or overfit signals + Bayesian shrinkage), `tips/meta_label.py` (López-de-Prado
  ACT/ABSTAIN — pure-numpy OOF logistic; predicts P(call correct), never direction), `tips/ensemble.py`
  (DECORRELATED weighted fusion via the existing ZCA combiner, never an agreement count).
- **Data layer (Wave 1):** `models.Bar` + `store/bars.py` (multi-timeframe BarStore + resampler),
  Upstox candles (`ingest/upstox.get_candles`), `ingest/candle_cache.py`, `live/bar_aggregator.py`
  (recorded spot ticks → bars), instrument-master key/option resolution + dump fetch, CLI
  `anvil data fetch-candles|fetch-instruments|build-bars`.
- **Momentum end-to-end (Wave 2):** `tips/series.py` (cache-only time-series block — never fetches on a
  live tick) threaded through `tips_for_chain`/`predict_for_chain`; `tips/momentum.py` +
  `GET /api/momentum/{u}`; the live loop and EOD cycle now build the series so momentum fires
  automatically (watchlist until certified).
- **One running cockpit (Wave 0):** `live/supervisor.py` (`LiveSupervisor` = cockpit predictions +
  always-on recorder + nightly moat clock + heartbeat, reusing the standalone functions — no fork),
  `api/buildinfo.py`, `GET /api/cockpit/status`, extended `/health`, and **`anvil go-live`** (REST +
  supervisor in one process). Config flags `ANVIL_LIVE_SUPERVISOR`/`cockpit_*`.
- **Tests:** ~110 new, full suite green (excl. the slow `tip_backtest`), ruff clean.
- **Still open (next sessions):** wire ensemble/meta-label/constituents into the live prediction path
  (needs accrued resolved history to train OOF); Wave 4 live single-stock option chains; Wave 5
  full-depth re-cert (streaming archive + ProcessPool → clears Harvey-t honestly); Wave 6 paper-live;
  the cockpit front-end header (DEMO/LIVE + build-stamp + gate chip) + a Momentum tab.

---

## 5. Current state (what works now)

- **Decision Brief** per underlying (environment verdict + VRP/regime/crush + P(touch) strike table),
  computed live on demo/real data; served at `/api/decision-brief/{u}` and shown atop the Tips tab.
- **Predictions + tips:** never-empty per-underlying prediction; index-option tips + single-stock
  BUY/SELL tips; measured reliability/track-record; "Edge-verified ✓" earned via the gate.
- **Calibration spine:** forecasts (market-implied, tip, **structural touch/VRP**) each on their own
  firewalled curve; touch labels accrue per strike×horizon×day.
- **Honest dormancy:** on ~3 months of data nothing clears the full DSR/PBO battery, so headline/
  edge-verified is rare by design — the always-on prediction + the decision brief carry the product.
- **Runs:** `anvil serve` (PWA + API on :8011), `anvil decision-brief NIFTY`, `anvil data
  fetch-closes`, `anvil tips backtest|run-eod|run-live`, `anvil paper`.

---

## 6. Future waves (planned — see the trackers for the live list)

Ordered in [`future_waves_of_upgrade.md`](../../future_waves_of_upgrade.md); the current top priority is
in [`next_wave.md`](../../next_wave.md). Summary:
- **W2.5 Validation/Data:** multi-year NSE + BSE bhavcopy (SENSEX), full equity-OHLC/VIX/FII-DII/
  participant-OI/earnings history → **validate** the touch/VRP/regime cells so ✓ can light up; the
  Decision-Brief `--record` + touch-resolution loop to accrue the structural reliability curve.
- **W3 Stock structural:** touch-prob + VRP + regime per single stock (large/mid/bluechip).
- **W4 ML meta-layer:** LightGBM as a *meta-layer* over the structural targets + path/dynamics
  features → calibrated **act/abstain** (meta-labeling), pure-numpy fallback. **Not** a direction oracle.
- **W5 News/sentiment · W6 AI research loop (LLM proposes features → harness validates) · W7
  ensemble/regime stacking · W8 transparency leaderboard UI · W9 intraday.**
- **Parked:** LLM-via-claude-CLI explanations (polish; never load-bearing/multi-user — ToS).

---

## 7. Run & verify

```bash
cd anvil
.venv/Scripts/python -m pytest -q && .venv/Scripts/python -m ruff check anvil   # 300+ pass, clean
.venv/Scripts/python -m anvil.cli data fetch-closes --symbols ^NSEI,^NSEBANK,^INDIAVIX --range 2y
.venv/Scripts/python -m anvil.cli decision-brief NIFTY            # environment verdict + P(touch) table
.venv/Scripts/python -m uvicorn anvil.api.app:app --host 127.0.0.1 --port 8011   # PWA + API
cd web && npm run build                                           # tsc + vite → anvil/api/static/
```
After a backend code change, **restart `uvicorn`** (it holds code in memory) and hard-refresh the PWA
(Ctrl+Shift+R) once so the new bundle/service-worker takes over.

## 8. Invariants & decisions (must not regress)
- **Honesty contract:** calibrated probabilities only; "accuracy" is measured from the ledger;
  abstain rather than fabricate. (ADR [0004](decisions/0004-calibration-first-compliance.md).)
- **Source-class firewall:** `seed`/`demo`/`paper`/`tip_*`/`struct_*` never blend into
  `PUBLIC_CLASSES`. Enforced by tests. Calibrators are also keyed `(target, source_class)` so a
  `tip_backtest` map never drives a `tip_live` prediction.
- **Calibration never feeds the gate:** the gate's `win_rate≥conviction` check tests the engine's RAW
  native confidence; calibrating that input would make it pass by construction. Calibrated probability
  is display/threshold only; sizing runs off the raw edge. Calibration quality is measured OUT-OF-FOLD.
- **Leak-safety:** every backtest read goes through `AsOfContext` (raises on look-ahead); the one
  rolling feature excludes day `d`.
- **Black-76 on futures** (ADR [0002](decisions/0002-greeks-black76-on-futures.md)); **never spot-BSM**
  (single-stock options are not priced/traded — ADR [0005](decisions/0005-bsm-on-spot-deferred.md)).
- **Honest framing (enforced):** no unconditional accuracy headline — "accurate" is conditional on
  coverage and shown on the reliability curve; the ADR tree stays contiguous. Guarded by
  `tests/test_docs_honesty.py` (ADR [0004](decisions/0004-calibration-first-compliance.md);
  [`METHODOLOGY.md`](METHODOLOGY.md)).
- **Pandas-free; pure-numpy** for new quant on the 3.14 venv.

## 9. Related docs
[`README.md`](../README.md) (run) · [`PITCH.md`](PITCH.md) (thesis) ·
[`METHODOLOGY.md`](METHODOLOGY.md) (trust & methodology) · [`hypothesis.md`](hypothesis.md)
(research blueprint) · [`decisions/`](decisions/) (ADRs) · [`DEPLOY.md`](DEPLOY.md) ·
[`SECURITY.md`](SECURITY.md) · [`Anvil wave2 challenge`](Anvil%20wave2%20challenge) (the W2 red-team).
