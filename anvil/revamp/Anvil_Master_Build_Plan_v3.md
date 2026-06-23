# Anvil — Master Build Plan v3 (code-grounded, post-audit)

*Supersedes `revamp/Anvil_Build_Plan.md` and fuses `revamp/W3.md`. Every claim below is grounded in a file-level audit of the real repo, not inference. Read `revamp/Anvil_Research_Report.md` for the evidence base and `docs/hypothesis.md` (the team's own blueprint, which agrees with it).*

---

## 0. North Star & the honest mechanism

**Goal: maximum operator P&L** from acting on Anvil's live, sized tips on Indian index options (NIFTY, SENSEX; BankNifty monthly) and stocks.

The only honest lever to more money is more **provable edge, sized to survive**:

> **P&L = provable edge × honest sizing × survival × execution.**

You cannot grow P&L by aiming at the money number — optimizing backtest P&L directly *is* the overfitting trap. You grow it by (a) proving edge through a gate you can trust, (b) sizing it with ruin control, and (c) abstaining when there's no edge. This plan maximizes those. "70–80%" is reframed, per Anvil's own `hypothesis.md`, as **high accuracy *when the engine speaks*, on a disclosed-coverage subset, shown on a live reliability curve** — a defensible ~62–68% on ~10–20% coverage, not an unconditional headline.

---

## 1. Confirmed decisions (locked)

- **Personal advice behind a HARD WALL.** Actionable buy/sell/sized/target language is owner-only, behind an identity/auth boundary — *not* a regex and *not* a tier label. The compliance-safe analytics surface (ADR 0004) stays the public default. (New ADR 0006.)
- **Honest money layer.** PnL is out-of-sample/walk-forward only (already true in code — keep it). Sizing = fractional Kelly **+ edge-uncertainty shrink + CVaR/tail cap**, with **risk-of-ruin and forward-drawdown distribution shown**. No in-sample hero curve (already absent — keep it that way).

---

## 2. What the audit changed (the headline)

The team built something genuinely strong and honest: real look-ahead guards (`AsOfContext` raises on future reads, enforced by tests), a source-class firewall, walk-forward net-of-cost resolution, a productionized Upstox OAuth + live loop, and lot-aware sizing on the post-2024 regime. **But the moat has holes, and a "calibration-first" engine that never calibrates.** These reorder the plan.

| Finding (file:line) | Implication | Fix phase |
|---|---|---|
| `n_trials = len(cells)` (`aggregate.py:68`) — not configs tried | Deflated-Sharpe doesn't deflate for researcher search → gate is gameable | **P0** |
| Day-blocking (`cell_from_daily`) only on touch path; options/equity gates use per-trade n (`tip_backtest.py:85`, `equities.py:226`, `store.py:200`) | Correlated same-day tips inflate t-stat/DSR on the money paths | **P0** |
| CPCV (`combinatorial_purged_splits`) never called in certification | "Purged CV" pillar is decorative; leak-safety = `AsOfContext` only | **P0** |
| No isotonic/Platt/conformal anywhere | "Calibration-first" product measures calibration but never performs it | **P2** |
| Targets correlated (all key off `atm_iv`/`total_gex`) | Naive agreement-count ensemble double-counts vol/gamma | **P2** |
| Sizing: fixed 0.55 Kelly, no edge-shrink, no CVaR cap, no ruin; `mc_pnl` distribution not attached | Over-sizes on uncertain/pre-cost edge; tail invisible | **P4** |
| No `PERSONAL_MODE` wall; actionable tips already on public tier | Currently past the ADR-0004 line; wall unbuilt | **P4** |
| 62 bhavcopy days; NIFTY-only closes; backfill unrun/un-hardened | Gate can't certify; SENSEX has no EOD path | **P1** |
| No always-on chain recorder (only inside manual `run_live`) | Irreplaceable OI/IV history lost daily | **P1 (urgent)** |
| Groww (execution broker) dead on Python 3.14 | Execution path needs 3.12 Docker or drop Groww | **P1 note** |

**Bottom line: the path to trustworthy live tips is gate-bound *and* data-bound** — the docs say "data-bound, not code-bound," but the gate holes mean any current `edge-verified ✓` is suspect. Fix the moat before building on it.

---

## 3. The re-sequenced plan

Order changed from W3. Rationale: everything downstream (selective prediction, sizing, the money meter) trusts the gate and the calibration. So the gate and calibration come before new signals, and data runs in parallel because it's time-bound.

### Phase 0 — Harden the moat (NEW; do first; blocks trust in everything)

Surgical fixes, no math rewrite — the four statistical primitives (PSR, DSR, CSCV-PBO, Harvey-t) are individually correct; they're just fed the wrong inputs.

1. **Count real trials.** Add a persisted experiment/trial registry (a DuckDB table) that monotonically counts every config/threshold/target sweep evaluated against the dataset. In `aggregate.validate_cells`, set `n_trials = max(len(cells), trials_logged)` and feed PBO the tried-config matrix, not just surviving cells.
2. **Route the money gates through `cell_from_daily`.** `tip_backtest.py`, `equities.run_equity_backtest`, and `IssuedTipStore.resolved_cells` must aggregate to one statistic per day (effective-n = independent days) before `validate_cells`, exactly as the touch path already does.
3. **Wire CPCV into certification.** Call `combinatorial_purged_splits` / `purged_walk_forward_splits` in the gate; enforce `embargo ≥ label horizon` (thread the tip horizon into the embargo).
4. **Tidy the deflation:** stop pooling cross-family Sharpes for `sr_variance`; fix the single-cell optimistic-variance floor; add a freshness/model-version check to `gate.decide_tier` so stale green verdicts can't persist.

**Definition of done:** plant a deliberately overfit cell + sweep a threshold → the gate's bar **rises and rejects it** (regression test). Re-run the existing Sep–Nov cells; expect *fewer* green than before (honest). 300+ tests still pass; new tests for trial-counting and day-blocking on all three engines.

**Claude Code task:** *"Add an experiment/trial registry and thread an honest `n_trials` into `backtest/aggregate.validate_cells` and PBO. Route `tip_backtest`, `equities`, and live `resolved_cells` through `cell_from_daily` so significance uses independent-day counts. Wire `combinatorial_purged_splits` into certification with `embargo ≥ horizon`. Add regression tests proving a threshold sweep raises the DSR bar. Don't change the statistical formulas."*

### Phase 1 — Data unlock + always-on recorder (run in PARALLEL with P0)

1. **Stand up the always-on intraday option-chain recorder NOW.** `recorder.TickRecorder` + `store.SnapshotStore` already persist per-strike OI/IV; they just need a standalone scheduled poller (Windows Task Scheduler or a tiny always-on loop) instead of only running inside manual `run_live`. This is the single most time-urgent item — that history is unbuyable and lost daily.
2. **Harden + run the 24-month NSE backfill.** `anvil backtest fetch --start --end` exists and the read path is fully point-in-time; add resume-from-last-cached, retry/backoff, polite parallelism for the ~500-request anti-bot pull. Exercise the pre-2024 legacy schema (currently untested — cache starts 2025-09).
3. **Backfill closes for all three indices** (yahoo supports `^NSEI`/`^NSEBANK`/`^INDIAVIX`; only NIFTY cached).
4. **Decide SENSEX:** build a BSE bhavcopy ingestor (no BSE URL exists today) or accept SENSEX is live-only/uncertifiable for now. **BankNifty is monthly-expiry only** (weeklies discontinued Nov 2024) — model its cells on monthly expiries.
5. **Wire `daily.py` (the EOD "moat clock") into the scheduler** to accrue the live reliability curve continuously.

**Definition of done:** ≥24 months NSE cached and reconciled; recorder running on a schedule; closes for NIFTY+BANKNIFTY+VIX; a written decision on SENSEX.

### Phase 2 — Calibration layer (the missing heart of "calibration-first")

1. **Pure-numpy PAV isotonic + Platt fallback** mapping each target's raw score → calibrated probability, fit on the already-collected `struct_live` resolved history, refit on a cadence. (scipy *is* available; scikit-learn is not — so PAV in numpy.)
2. **Per-target calibration, then decorrelated combination.** Calibrate touch / VRP / equity-factor probabilities *separately* (per-target reliability curves), and **whiten/decorrelate the shared `atm_iv`/`total_gex` inputs** before combining — no naive agreement count.
3. **Adaptive/temporal conformal** for honest, distribution-free coverage and a **risk-calibrated abstain threshold** that replaces the hard-coded magic numbers (`decision_brief` 0.62/0.45, `iv_crush` 66). Use a time-series-adaptive variant (exchangeability is violated) and recalibrate.

**Definition of done:** per-target reliability curves near-diagonal (ECE < 0.10) on resolved history; stated p ≈ realized frequency; abstain threshold set from measured coverage, not constants.

### Phase 3 — Gate-0 re-certify (the kill switch)

With the fixed gate (P0) + real data (P1) + calibration (P2): walk-forward, per target, **threshold chosen inside the loop and counted as a trial** — does the high-confidence bucket sustain honest accuracy at usable coverage?

**Pass bar:** at least one target sustains **≥ ~65% calibrated accuracy at ≥ ~10–15% coverage** with DSR ≥ 0.95, PBO ≤ 0.5, Harvey t ≥ 3, trials counted. Report per-target accuracy–coverage curves.

**Go/no-go:** pass → build the money/UI layer with confidence. Fail → consciously accept a lower accuracy at higher coverage, or abstain in that regime. **Do not build P4/P5 until Gate-0 passes** — this is what stops you spending months on a dashboard for an edge that isn't there.

### Phase 4 — Honest money layer + hard wall (only after Gate-0)

1. **Fix `strategy/sizing.size_units`:** add **edge-uncertainty shrink** (shrink `edge_prob` toward 0.5 by its std-error / sample count), a **CVaR/tail cap** as a fourth binding term, size on **cost-adjusted** EV (not gross), and a **broker-margin feasibility cap**. Unify the two divergent `SizingConfig`s (`generate.py` vs `equities.py`). Make naked-structure `max_loss` a **CVaR-based true tail**, not the stop multiple.
2. **Attach the distribution to every ticket:** wire `engine.montecarlo.mc_pnl` (EV percentiles, VaR/CVaR) onto the `Tip`/`Prediction`, and add **risk-of-ruin + forward-drawdown distribution**. Show these, not a point-₹ hero number.
3. **Build the `PERSONAL_MODE` hard wall:** `ANVIL_PERSONAL_MODE` in `config.py`; actionable legs/targets/sized language emitted **only** behind owner-only auth (`api/routers/*`, `auth/deps.py`); public default exposes analytics (`Prediction` without `actionable_tip`); keep `check_compliance` as the default block. Document as ADR 0006.

**Definition of done:** every high-conviction call renders an honest sized ticket (direction, fractional-Kelly+shrunk+capped lots, entry/stop/target, max-loss ₹, EV distribution, P(ruin), drawdown); public surface is ADR-0004-clean; personal surface owner-gated and walled.

---

#### Appendix P4.A — "Upstox real-time trading simulation" (Anvil Live v2): parallel build, assessed 2026-06-22

A separate build session produced a `realtime_sim/*_v2` module family that already implements much of this Phase-4 thesis — but for **VRP-driven option STRUCTURES**, not directional tips. What it added:

- **`engine_v2.py`** — live VRP (ATM IV vs realized vol), GEX/zero-gamma regime, and a **physical (VRP-adjusted) terminal distribution** for POP/EV. Pure-stdlib port of `strategy/context` + `engine/{gex,regime,implied_dist}`.
- **`structures_v2.py`** — builds & prices real iron condors, short strangles, credit/debit spreads, straddles; each scored by net credit, **3σ stress max-loss for naked**, physical POP, and **EV net of the full India F&O cost stack**.
- **`costs_v2.py`** — conservative India cost stack (current 0.10% options-sell STT), spread-crossing fills.
- **`sizing_v2.py`** — min(risk-fraction, fractional-Kelly, exposure, lot-cap) with **short-vol Kelly hard-capped at 0.10** (negative-skew guard) — exactly the Phase-4 Kelly-safety item.
- **`gate_rank_v2.py`** — ACTIONABLE/WATCH/ABSTAIN gate with **regime-fit** + a **portfolio correlated short-vol stress cap**; conviction stays RAW into the gate (no calibration circularity).
- **`tracker_v2.py`** — logs ideas, resolves at expiry settlement, with **mandatory tail stats** (maxDD, worst day/trade, CVaR5%, Calmar, Sortino), MAE/MFE + modeled-stop, VRP audit, open-excluded-but-counted, cash benchmark. Edge **measured, never asserted**.
- **`backtest_v2.py`** — a **real, non-circular VRP prior**: sell the India-VIX-priced 1-day ATM NIFTY straddle vs realized next-day move (parameter-free, causal, ~2y incl. stress). Explicitly NOT a track record of the live structures.
- **`live_v2.py` + `serve_v2.py`** — full live cycle (feed → state → structures → gate+size → portfolio cap → rank → log → resolve → scorecard + VRP prior) and a stdlib browser dashboard.

**Maps to Phase 4:** delivers items 1–2 in spirit (cost-adjusted EV, stress/CVaR tail caps, short-vol Kelly safety, distribution-on-every-ticket via the physical grid) **and** the Research Report's #1 recommendation (VRP harvesting). It does **not** yet implement item 3 (the `PERSONAL_MODE` owner-gated hard wall) — that remains.

**Measured results (live + backtest, 2026-06-22, market open):**
- Live read, 13 underlyings: per-name regime + VRP, e.g. NIFTY VRP≈1.00 NEUTRAL, BANKNIFTY 1.39 BUY_VOL, RELIANCE 0.81 SELL_VOL, TCS 1.75 BUY_VOL. Tip sheet: **0 ACTIONABLE / 1 WATCH / 66 ABSTAIN** — heavy abstention, correctly (fresh book, edge unproven).
- **VRP prior backtest (real, non-circular, 492 trading days):** win-rate **65.2%**, ≈**+16.1%/yr** on ₹1M, **Sharpe 1.89**, profit-factor 1.37; **tail: maxDD −13.7%, worst-day −2.8%, CVaR5% −₹14.5k**; realized/implied averaged **0.84** (premium structurally rich). A genuine, documented edge — *unlike* the v1 directional model (~49% hit-rate, negative after costs).

**Build-on actions taken now:** the v2 session's `config.V2_*` constants and the client's `option_chain_by_key` (stock-F&O chains) had been lost to a filesystem write issue; both were restored, config de-duplicated into one canonical block, and the full pipeline re-verified live (indices + 10 F&O stocks) plus the VRP backtest reproduced.

**Assessment / recommendation — build on v2, not v1.** The VRP-structure approach is the credible edge and aligns with both this plan and the Research Report. BUT it stays **gate-bound by Phase 3 / Gate-0**: the +16%/yr is a *prior* on a clean proxy, not a certified live track record, and it is short-vol (sells insurance → fat left tail). So: keep ACTIONABLE gated behind measured forward resolution (`tips_v2.db` accruing), keep the mandatory tail stats, add the item-3 `PERSONAL_MODE` wall before any sized/actionable language ships, and do **not** let the attractive backtest short-circuit Gate-0. Promote v2 from WATCH to ACTIONABLE only when the live cells clear the gate.

### Phase 5 — Live sized tips loop (the goal, delivered)

`live/live_runner.run_live` already does live chain → prediction + gated tip → ledger → equity → SSE. Now it emits **calibrated, gated, honestly-sized personal tickets on live data**, with the reliability curve + accuracy-at-coverage as the trust dial, and `daily.py` accruing the live track record. Tips appear **only when the calibrated gate fires** — expect silent days; the money is in sizing the few good calls well, not in call volume.

**Definition of done:** on live data, sized personal tips surface when (and only when) the gate fires; coverage logged; reliability curve updates continuously.

### Phase 6 — Docs / ADRs / identity (true parts now; defer the rest)

- **`ANVIL.md` §1: fix the self-contradiction now.** The line *"Sustained 70–80% directional accuracy is the main goal"* contradicts Anvil's own `hypothesis.md`. Replace with the honest selective framing: *"High accuracy when it speaks — a calibrated, disclosed-coverage subset on a live reliability curve; goal = operator P&L."* Keep "No fabricated accuracy."
- **ADR 0005 (BSM-on-spot):** only if single-stock physically-settled options are actually traded (low priority; index path is correctly Black-76).
- **ADR 0006 (personal-mode hard wall):** as above.
- **Defer** the monetization/identity *memory* edits until Gate-0 passes — don't make a reversible strategic pivot sticky before it's proven.

---

## 4. What NOT to do (resist the churn)

- **Don't revamp the engine.** The spine is sound; the wins are surgical (gate inputs, calibration, sizing safety, the wall). A rewrite is months of churn for zero edge.
- **Don't add deep nets** (LSTM/TFT/N-BEATS). Both my research and `hypothesis.md` agree they don't beat simple baselines after costs at these horizons; GBM-optional + calibrated quant is the move.
- **Don't trust any current `edge-verified ✓`** until Phase 0 lands.
- **Don't chase call volume.** Correlated index strikes aren't independent breadth; more cells = more multiple-testing penalty once trials are counted honestly.

---

## 5. Inputs needed from you

1. **Run the recorder on a schedule** (your machine, Task Scheduler) — start today; the OI/IV history is unbuyable.
2. **Capital figure** — drives sizing honestly (one NIFTY lot ≈ ₹15–20 lakh notional; expect 0–1 lots per spread on modest capital).
3. **SENSEX decision** — build the BSE bhavcopy ingestor, or treat SENSEX as live-only/uncertifiable for now.
4. **Execution broker** — Groww needs the 3.12 Docker image to run; Upstox OAuth is already productionized. Decide whether execution stays Upstox-only.
5. **Optional paid data** — TrueData/GDFL quotes for historical options-with-Greeks if you want depth faster than the free NSE backfill; not required to start.

---

## 6. The honest bottom line

Anvil is ~80% of a genuinely excellent, honest engine — and it's much further along than W3 or my first plan assumed. The gap to *trustworthy, live, sized tips you can profit from* is not a rewrite and not a new model. It is: **fix the four moat holes, get the data + recorder running now, add the calibration the "calibration-first" product is somehow missing, prove it with the fixed gate, then turn on honest sized personal tips.** That maximizes provable edge and disciplined sizing — which is the only real road to maximum P&L. If, after the fixed gate on real data, the edge still won't certify, that is the market telling the truth, and Anvil's ability to abstain on it is exactly what will keep your capital intact while 91% of F&O traders lose theirs.
