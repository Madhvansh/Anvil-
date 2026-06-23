# Anvil — NEXT WAVE (highest priority)

> Single source of truth for "what to build next." This file outranks every other backlog.
> Full backlog + cited research: `future_waves_of_upgrade.md`. Plan: `~/.claude/plans/anvil-short-term-trading-snuggly-pascal.md`.

---

## STATUS (updated 2026-06-23) — W2 shipped; master-plan Phases 0–6 shipped

W2 (below) is **shipped**. Since then the live roadmap moved to `anvil/revamp/Anvil_Master_Build_Plan_v3.md`
and **Phases 0–6 all shipped**: P0 gate-hardening → P1 data + recorder → P2 calibration → P3 Gate-0 kill
switch → P4 honest sizing + the personal-mode hard wall → P5 live sized-tips loop + trust dial → **P6
docs/ADRs/identity (the honest-framing pass — this just landed)**. Full record in
[`docs/ANVIL.md`](anvil/docs/ANVIL.md) §4.

**Current top priority is data-bound, not code-bound: full-depth Gate-0 re-certification.** The 24-month
bhavcopy backfill landed (624 days), but the conviction cell abstains on a single constraint —
**Harvey t ≈ 2.64 < 3.0** (only ~12 independent days in the windowed cert). To clear it: (1) build the
**chunked/streaming `BhavcopyArchive` loader** so a full-depth cert doesn't OOM, then re-run `anvil gate0`;
(2) **run the moat clock + recorder on schedule** (Task Scheduler) to accrue independent-day live
evidence. The sized-tips wall (`personal_mode_armed`) auto-arms the moment a cell certifies — no code
change. Until then it stays honestly dark. *(W2.5 Validation/Data, below, is exactly this.)*

---

## SHIPPED — W2: Buyer Decision-Brief Engine (probability-of-touch, environment-gated)

**Why:** stop building dark engines. Reframe the target from daily index *direction* (least achievable/useful/safe) to the buyer's real questions — **probability-of-touch**, **VRP/IV-richness**, **event IV-crush**, **regime** — surfaced *now* as a rich honest **Decision Brief** (environment-gate → strike-action), with **abstention first-class**. ML/GBM is demoted to a later meta-layer built *after* data.

**Shape:** one unified Decision Brief. Lead read = P(touch K within T) (VRP-adjusted to the real-world measure) vs the option's implied move. Gating band = VRP + regime + IV-crush → FAVORABLE / NEUTRAL / UNFAVORABLE / ABSTAIN (+ a `flip_condition`). Honest: "analytics, not edge-proven" until cells clear `validate_cells`.

### Build order — SHIPPED (W2 core complete)
- [x] Task 0 — this file + `future_waves_of_upgrade.md`
- [x] `engine/touch_probability.py` — shared GBM ensemble (C13), **Brownian-bridge correction (C1, test passes reflection ±0.02)**, ATM-IV default (C12), **live `vrp_ratio` physical read (C2)**, vol-only note (C14)
- [x] `engine/realized_vol_forecast.py` — **Garman-Klass RV (C4)**, HAR-RV/EWMA, **VRP as a resolvable probability (C7)**, **horizon-matched IV/RV (C5)**
- [x] `engine/term_structure.py` — front/next IV slope → backwardation/crush window; expected move ≈ 0.85×ATM straddle
- [x] `engine/regime_score.py` — multi-signal **agreement count (C9, NO accuracy %)**
- [x] `engine/decision_brief.py` — compose env-gate → strike-action; **`flip_condition` (C10)**
- [x] `ledger/ledger.py` — `KIND_PROB_TOUCH` + `KIND_VRP_RICH` + `STRUCTURAL_CLASSES` firewall + `emit_structural_forecasts`; **`aggregate.cell_from_daily` day-block significance (C3)**
- [x] `ingest/yahoo.py` — pandas-free Yahoo chart JSON OHLC + `^INDIAVIX`; **IST trading-date discipline (C6)**; csv cache
- [x] API `/api/decision-brief/{u}` + CLI `anvil data fetch-closes`, `anvil decision-brief [--record]`
- [x] UI — **plain `DecisionBriefCard` TABLE first (C11)** at top of Tips tab; bespoke charts deferred
- [x] Tests: test_touch_probability / _realized_vol_forecast / _term_structure_regime / _decision_brief / _touch_calibration / _yahoo_ingest; ruff + web build green

### Remaining polish (optional, this wave)
- Bespoke charts (`TouchProbCurve`/`VRPGauge`/`EnvironmentBand`) — deferred per C11 (table delivers the content).
- `--record` nightly cycle + a resolution loop (touch from realized daily high/low) to accrue the struct calibration curve. Front+next-expiry term-structure (currently front-only unless `next_chain` passed). Constituents/earnings seed expansion.

### Must-fix invariants (verified)
- **C1** bridge-corrected touch — reflection test tight ±0.02, monotonic in horizon ✓
- **C2** physical read uses the *live* `forecast_RV/ATM_IV`; static `paper_vrp_ratio` = labeled fallback ✓
- **C3** calibration per-label; **significance/edge gate on day-level blocks** (effective-n = independent days) ✓

## AFTER THIS WAVE → W2.5 VALIDATION/DATA
Heavy multi-year NSE bhavcopy + BSE (SENSEX); full equity-OHLC/VIX/FII-DII/participant-OI/earnings history → validate touch/VRP/regime cells so the ✓ badge can light up. Then W3 per-stock structural, W4 ML meta-layer. See `future_waves_of_upgrade.md`.
