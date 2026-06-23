# Extending Anvil — Architecture + Claude Code Build Plan

*Companion to the research report. Goal: extend the existing Anvil engine (keep the CPCV gate, ledger, Black-76, HAR-RV) toward genuine post-cost edge and honest conditional accuracy. Build order is by ROI and dependency, not by glamour.*

---

## 0. Design principles (the rules every phase obeys)

1. **The gate is the boss.** Nothing ships to "tips" until it clears the existing certification gate (n≥50, calibration ≥ conviction, post-cost edge>0, Harvey |t|≥3, Deflated Sharpe ≥0.95, PBO ≤0.5, bootstrap 5th-pct>0). New code *feeds* the gate; it never bypasses it.
2. **Headline = conditional accuracy at disclosed coverage + post-cost edge.** Never an unconditional hit-rate. The scoreboard (§Phase 3) replaces "accuracy."
3. **Count every trial.** Each model/hyperparameter sweep increments the trial counter that the Deflated Sharpe and PBO consume. Self-deception is the enemy; the trial count is the antidote.
4. **Leakage is failure.** Purge + embargo on every split; features are as-of-timestamped; no feature may use information after the decision time. The label clock and the feature clock are separate and audited.
5. **Quant-primary, ML-meta.** Primary signals stay rule-based and interpretable. ML enters only as a *bet/no-bet* meta-layer and a *calibration* layer — the configuration the evidence says actually helps.
6. **Synthetic stays firewalled.** Keep the `source-class` discipline: real-EOD/recorded data only in certification; synthetic/demo for plumbing tests, never in the ledger.

---

## 1. Target architecture (extends current Anvil)

```
                          ┌─────────────────────────────────────────┐
                          │                DATA LAYER                 │
   NSE UDiFF/EOD ───┐     │  anvil/data/                              │
   India VIX ───────┤     │   ingest_nse.py   (history + UDiFF seam)  │
   Option-chain ────┼────▶│   chain_recorder.py (poll & store live)   │
   Broker ticks ────┤     │   broker/{kite,upstox,angel}.py           │
   GDELT/cal ───────┘     │   news_events.py                          │
                          └───────────────┬───────────────────────────┘
                                          ▼
                          ┌─────────────────────────────────────────┐
                          │           FEATURE LAYER (as-of)          │
                          │  anvil/features/                          │
                          │   har_rv.py (realized vol, regimes)       │
                          │   chain_features.py (OI/IV/PCR as feats)  │
                          │   event_flags.py (RBI/Budget/results)     │
                          │   reversal.py, intraday_momo.py           │
                          └───────────────┬───────────────────────────┘
                                          ▼
        ┌──────────────────────┐   ┌──────────────────────┐
        │  PRIMARY SIGNALS      │   │   REGIME GATE         │
        │  (existing, kept)     │   │  anvil/regime/        │
        │  Black-76, momentum,  │   │   hmm_vol_regime.py   │
        │  HAR-RV, VRP cells    │   │  (NIFTY≠BANKNIFTY)    │
        └──────────┬───────────┘   └───────────┬──────────┘
                   ▼                            │
        ┌──────────────────────────────────────▼──────────┐
        │   META-LAYER  anvil/meta/                         │
        │   triple_barrier.py  → labels                     │
        │   meta_model.py (LightGBM bet/no-bet)             │
        │   importance.py (MDA, purged)                     │
        └──────────────────────────┬───────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────┐
        │  CALIBRATION + SELECTIVE PREDICTION               │
        │  anvil/calibration/                               │
        │   calibrate.py (isotonic/Platt)                   │
        │   conformal.py (adaptive/temporal)                │
        │   selective.py (risk–coverage, abstain)           │
        └──────────────────────────┬───────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────┐
        │  SIZING + TAIL BUDGET  anvil/sizing/              │
        │   vol_target.py, tail_budget.py (CVaR caps)       │
        └──────────────────────────┬───────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────┐
        │  CERTIFICATION GATE (existing) + SCOREBOARD       │
        │  anvil/backtest/validation.py (CPCV, DSR, PBO)    │
        │  anvil/scoreboard/ (Brier, reliability, R–C curve)│
        │   → anvil_store.duckdb / anvil_ledger.duckdb      │
        └──────────────────────────────────────────────────┘
```

Everything above the gate is new or extended; the gate, ledger, and source-class firewall are reused unchanged.

---

## 2. Phased build — what to ask Claude Code, in order

Each phase has: **Goal · New modules · Claude Code task (paste-ready) · Definition of done · Guardrail.** Do not start a phase until the prior phase's "definition of done" is met.

---

### Phase 0 — Data foundation (1–2 weeks)
**Goal:** multi-year history loaded + live option-chain recording started. This is the single highest-ROI phase because your audit's own conclusion is "the unlock is more history, not a new model."

**New modules:** `anvil/data/ingest_nse.py`, `chain_recorder.py`, `broker/kite.py` (or angel/upstox), `news_events.py`.

**Claude Code task:**
> "In the existing Anvil repo, add an `anvil/data` package. Implement `ingest_nse.py` to download and normalize multi-year NSE F&O daily-settlement/UDiFF files and index/stock EOD into the existing DuckDB store, handling the pre/post-July-2024 bhavcopy schema change as an explicit adapter with tests. Implement `chain_recorder.py` that polls the NSE option-chain JSON for NIFTY/BANKNIFTY/SENSEX/FINNIFTY on a schedule and appends timestamped per-strike OI/IV snapshots to a new `option_chain_snapshots` table (idempotent, dedup on (symbol, expiry, strike, ts)). Add `broker/kite.py` implementing a thin client for candle backfill + websocket ticks behind an interface `MarketDataSource` so upstox/angel can be swapped. Tag all rows with `source_class` consistent with the existing firewall. Write unit tests with recorded fixture payloads; no live calls in tests."

**Definition of done:** ≥3–5 years of EOD F&O + index history queryable; live chain recorder writing snapshots daily; schema-seam adapter tested; everything tagged by source_class.

**Guardrail:** start recording the option chain **now** — brokers don't sell per-strike OI/IV history, so every day not recorded is permanently lost.

---

### Phase 1 — Re-certify on history (no new model) (3–5 days)
**Goal:** run the *existing* walk-forward + gate on the new multi-year data. Convert "0 cells edge-verified" into honest verdicts with enough independent days for Deflated-Sharpe/PBO to mean something.

**New modules:** none — extend `anvil/backtest/tip_backtest.py` & `validation.py` to consume the longer history and to handle the **expiry-regime break** (pre/post 1-Sep-2025 weekly-expiry day change) as a regime split, not a pooled sample.

**Claude Code task:**
> "Extend the existing walk-forward backtest to run over the full multi-year history now in the store. Add an `expiry_regime` dimension encoding the two SEBI breaks: (a) ~Nov-2024 discontinuation of BankNifty/FinNifty/Midcap **weekly** options (NSE weeklies become NIFTY-only; BankNifty becomes monthly-only), and (b) the 2025-09-01 NSE Thursday→Tuesday expiry shift (BSE/SENSEX stays Thursday). Evaluate pre/post each break as separate regimes and **never pool across a break**; drop discontinued-product cells (e.g., BankNifty weekly) from forward certification. Re-run the certification gate per strategy cell and emit the same track-record table the evidence pack uses, plus the number of *independent* trading days per cell. Persist to `tip_validation`. Do not change the gate thresholds."

**Definition of done:** refreshed track-record table on multi-year data, segmented by expiry regime; discontinued-product cells excluded from forward certification; per-cell independent-day counts; any cell that clears the full gate flagged Edge-verified automatically.

**Guardrail:** if a cell still fails after more data, that is signal — log it, don't tune the gate to pass it.

---

### Phase 2 — Meta-labeling layer (bet / no-bet) (2–3 weeks)
**Goal:** raise precision on *taken* trades by adding a secondary model that vetoes low-quality primary signals. The evidence says this helps precisely when the primary is rule-based quant — which Anvil's is.

**New modules:** `anvil/meta/triple_barrier.py`, `meta_model.py`, `importance.py`.

**Claude Code task:**
> "Add an `anvil/meta` package. Implement triple-barrier labeling (profit-take / stop / max-hold) on the primary signals' entry events, with per-label sample-uniqueness weights for overlapping labels. Train a LightGBM meta-classifier that outputs P(primary signal is correct) from **orthogonal** features only — HAR-RV vol state, regime, event flags, calibrated option-chain features — explicitly excluding the primary signal's own raw inputs to avoid 'squeezing the same orange twice.' Evaluate with Combinatorial Purged CV + embargo. Report out-of-sample precision/recall on the taken subset and MDA feature importance under purging. Increment the global trial counter for every hyperparameter configuration tried."

**Definition of done:** meta-model improves OOS precision on taken trades vs. the unfiltered primary, measured under CPCV; importance report shows orthogonal features carrying the signal; trial count logged for the gate.

**Guardrail:** if meta-labeling does **not** beat the unfiltered primary OOS, keep the primary and discard it — that's the honest result, and the research shows it sometimes loses.

---

### Phase 3 — Calibration + conformal selective prediction + scoreboard (2–3 weeks)
**Goal:** make stated probabilities true (reliability curve on the diagonal) and produce the legitimate "70%": accuracy-at-coverage. This is your differentiator made real.

**New modules:** `anvil/calibration/calibrate.py`, `conformal.py`, `selective.py`; `anvil/scoreboard/`.

**Claude Code task:**
> "Add `anvil/calibration`. Implement isotonic and Platt calibration fit on a purged calibration window. Implement a **time-series-adaptive** conformal layer (adaptive conformal inference / temporal variant — NOT vanilla split conformal, because exchangeability is violated) that yields a confidence score per signal and recalibrates on a rolling cadence. Implement `selective.py` to produce the risk–coverage curve and an abstain decision at a configurable target coverage. Then add `anvil/scoreboard/` emitting the 5-part scorecard: (1) post-cost edge + Harvey t + Deflated Sharpe, (2) Brier + reliability curve, (3) conditional accuracy at coverage, (4) tail metrics (max DD, CVaR, worst trade), (5) abstention rate. Export the reliability curve and risk–coverage curve as data for the live public page."

**Definition of done:** reliability curve materially closer to the diagonal (Brier ↓ from ~0.251); a published risk–coverage curve; tips now carry both a calibrated probability and an abstain/trade decision; scoreboard replaces the accuracy headline everywhere.

**Guardrail:** coverage is always reported next to conditional accuracy. A high conditional accuracy with hidden coverage is the banned metric.

---

### Phase 4 — Regime gating + HAR-RV sizing (1–2 weeks)
**Goal:** fire signals only where they have demonstrated edge, and size by volatility. Convert weak unconditional signals into strong conditional ones.

**New modules:** `anvil/regime/hmm_vol_regime.py`, `anvil/sizing/vol_target.py`, `tail_budget.py`.

**Claude Code task:**
> "Add `anvil/regime` with an HMM / Markov-switching volatility-regime detector driven by HAR-RV and India VIX, fit per index with **NIFTY and BANKNIFTY kept separate** (BankNifty ≈1.3–1.5× vol). Expose a regime label to the meta-layer and a gate that suppresses signals in regimes where the cell has no certified edge. Add `anvil/sizing` with vol-targeted position sizing and a `tail_budget.py` enforcing CVaR / max-loss caps per trade and per book, so short-volatility cells cannot accumulate hidden steamroller risk."

**Definition of done:** per-index regime labels feeding the meta-model and gate; sizing scaled to forecast vol; explicit tail caps enforced and visible on the scoreboard.

**Guardrail:** never pool NIFTY and BANKNIFTY; a signal certified on one is not certified on the other.

---

### Phase 5 — Variance-risk-premium harvesting cells (2–3 weeks)
**Goal:** add the one peer-reviewed real edge — selling overpriced premium — *done right*, with the tail managed. This replaces "predict direction from PCR/max-pain" with something that actually has academic support.

**New modules:** `anvil/vrp/harvest.py` (new strategy cells), reusing existing Black-76 + the tail budget from Phase 4.

**Claude Code task:**
> "Add `anvil/vrp/harvest.py` implementing variance-risk-premium strategy cells (e.g., defined-risk short premium) that (a) prefer overnight holds where the NIFTY VRP is concentrated, (b) scale with the HAR-RV vol regime, (c) flag event windows (RBI/Budget/earnings) for reduced or defined-risk-only sizing, and (d) are hard-capped by `tail_budget.py`. Route every cell through the existing certification gate and the scoreboard; require defined-risk structures so worst-case loss is bounded and visible. Keep NIFTY/BANKNIFTY cells separate."

**Definition of done:** VRP cells that clear the gate on multi-year, post-2025-expiry-regime data with bounded tail; the option-chain layer now harvests a real premium rather than reporting folklore indicators.

**Guardrail:** no naked short premium into scheduled events; defined-risk only; the tail budget is non-negotiable.

---

### Phase 6 — Live reliability + coverage reporting (ongoing)
**Goal:** wire the scoreboard into the live public page so calibration and coverage are continuously, honestly visible — the moat your evidence pack already names.

**Claude Code task:**
> "Wire `anvil/scoreboard/` exports into the live public reliability page: rolling reliability curve, risk–coverage curve, abstention rate, and post-cost edge with Deflated Sharpe — all out-of-sample, all net of the cost model, updated as new outcomes resolve in the ledger."

**Definition of done:** a live page where anyone can see that when Anvil says 70%, it's ~70% — and how often it abstains.

---

## 3. How to drive Claude Code well (working agreement)

- **One phase per branch.** Each phase = a feature branch + tests + a short design note. Don't let Claude Code build two phases at once.
- **Test-first on the leakage-sensitive parts.** Ask for failing tests that assert no future information enters a feature, *then* the implementation.
- **Make the trial counter a first-class object.** Every sweep logs to it; the Deflated Sharpe reads from it. This is your single best defense against fooling yourself.
- **Demand CPCV everywhere there's a label.** If Claude Code proposes a plain train/test split on overlapping labels, reject it.
- **Ask for the boring version first.** GBM before any neural net. A neural sequence model is only on the table later, and only if you add L2 microstructure data and it beats the GBM baseline *after costs* under CPCV.
- **Keep the firewall.** Any new data path must carry `source_class`; synthetic data must be physically incapable of entering certification.
- **Acceptance = the gate + scoreboard, not a demo.** "It runs" is not done; "it cleared (or honestly failed) the gate and updated the scoreboard" is done.

A good kickoff prompt for Claude Code:
> "Read the existing Anvil codebase and the two attached documents (research report + this build plan). Confirm the current module layout, then implement **Phase 0** only: the `anvil/data` package per the build plan, with tests and a short design note. Do not touch the gate. List any assumptions you had to make."

---

## 4. What I need from you to unblock the build

1. **Broker API key** — Kite Connect (₹500/mo) recommended, or free Angel One / Upstox — for live recording + intraday backfill.
2. **Written quotes from TrueData *and* Global Datafeeds** for historical options-with-Greeks (both are sales-gated; we pick on price/coverage).
3. **Repo access** to the existing Anvil codebase so we extend, not rebuild.
4. **Confirm compute** — one modern machine (a single GPU is ample; we are GBM-first).
5. **Decision on the success metric** (you skipped it): I've defaulted to *post-cost edge + calibration, with conditional accuracy-at-coverage as the honest "70%."* Confirm or redirect.

---

## 5. Sequenced milestones (realistic, honest)

| Phase | Output | Proves |
|---|---|---|
| 0 | Multi-year history + live chain recorder | Data is no longer the bottleneck |
| 1 | Re-certified track record | Which cells have *any* real edge |
| 2 | Meta-labeling bet/no-bet | Higher precision on taken trades |
| 3 | Calibration + selective + scoreboard | Honest "70%" at disclosed coverage; Brier ↓ |
| 4 | Regime gating + sizing | Weak signals → strong conditional ones |
| 5 | VRP harvesting cells | A real, peer-reviewed premium, tail-managed |
| 6 | Live reliability/coverage page | The diligence-surviving moat, public |

**The honest promise:** this sequence maximizes post-cost expectancy, calibration, and *conditional* accuracy — the levers with real evidence. It does not promise a 70% unconditional headline, because that number is either fake or already sitting in your short-strangle cells doing nothing for you. If, after Phase 1–5 on multi-year data, the gate still won't certify positive post-cost edge, that is the market's verdict — and Anvil's ability to *abstain* on that verdict is exactly what makes it worth more than the tip-sellers who can't.
