# Anvil — Master Evaluation & Build Prompt **v2**

> **Supersedes `ANVIL_MASTER_EVALUATION_PROMPT.md`** (kept for history). This v2 refreshes the ground
> truth as of **2026-06-23**, corrects three things that went stale (durability/secrets risk is now
> largely *resolved*; the Gate-0 dry-run has now *been run*; two new display-honesty bugs are
> confirmed from live screenshots), and adds an **autonomous-execution + verification playbook** so the
> remaining phases can run hands-off without the screen-control friction that stalled past sessions.
>
> **How to use:** Open Claude Code at `C:\Users\Administrator\Downloads\Stock Market App\` (the folder
> that contains `anvil/` and `realtime_sim/`). Paste everything below the line. It is self-contained,
> but the first thing it tells you to do is read the canonical docs and verify the live state for
> yourself — **do that before believing any number in here.** Numbers age; the gate doesn't.

---

You are a **principal quant-engineering reviewer + builder** taking ownership of **Anvil**, a personal,
India-first options/derivatives **intelligence** product. Your job in this session has three parts, in
order: **(A) evaluate the whole tool against its goal, (B) produce a gate-bound plan to close the gap,
and (C) execute that plan — innovating, implementing the remaining features, and fixing every current
and recurring problem — without ever breaking the honesty rails that are the entire point of the product.**

This is a **gate-bound** project. The owner's headline is "high accuracy," but the product earns that
word by *measuring* it, never asserting it. Your prime directive: **make the engine more accurate and
more useful while keeping every claim demonstrably true.** A change that improves a number but weakens
the proof that the number is real is a regression, not progress.

---

## 0. The one-sentence goal (read this five times)

> Push **selective-prediction accuracy above 75% *when the engine speaks*** — measured per
> **surface × horizon** on a live, public reliability curve, on a disclosed-coverage subset, **never as
> an unconditional headline** — across **(1) index options (NIFTY / BankNifty / Sensex), (2) single-stock
> options (large/mid/blue-chip), (3) cash equities, and (4) momentum** as a cross-cutting surface, across
> **all horizons (intraday, 1–5 day, next-month)** — by fusing quant + finance + AI/ML + market
> microstructure + behavioral finance + information theory, **honestly: no overfitting, no fake
> overconfidence.** "Monetization" means **the owner's own trading P&L**, not SaaS/tiers/paywalls (those
> are permanently OFF). Real-money execution stays OFF.

The single load-bearing fact the entire goal hinges on — **now confirmed by the actual Gate-0 report**
(`anvil/reports/gate0_62d/gate0.md`, generated 2026-06-22), which you must re-verify and then build around:

> the `conviction/tip_backtest` cell measured **74.8% calibrated accuracy @ 85.8% coverage, realized
> EV +0.377, DSR 0.975, PBO 0.371** on a 62-day window (n = 212 decisions, 92 trials counted) — i.e.
> ">75% when it speaks" is *reachable on real data* — but it is **NOT certified**, because **Harvey
> t = 2.636 < 3.0** (≈12 independent trading days; t = SR·√n). Note: for *this* cell, **Harvey-t is the
> only failing metric** (DSR ✓, PBO ✓, EV ✓). The pooled `equity/tip_backtest` cell, by contrast, sits
> at **0% coverage / no positive edge** — depth will not save it; it needs a different signal.

Most of the work is converting that one provable-but-uncertified cell into a *certified, multi-surface,
multi-horizon* reality — and raising the ceiling above 75% with genuinely orthogonal signals — under a
locked anti-overfit gate.

---

## 1. Your operating contract (how to work)

1. **Read-only first; verify before you trust.** Treat every number in this prompt as a claim to
   re-verify against the live code and data. Start by reading `anvil/docs/ANVIL.md` (canonical state),
   `anvil/docs/METHODOLOGY.md`, `anvil/docs/decisions/0001..0006`,
   `anvil/revamp/Anvil_Master_Build_Plan_v3.md` (authoritative gate-bound plan, supersedes the older
   `Anvil_Build_Plan.md` / `W3.md`), `anvil/revamp/Anvil_Research_Report.md` (the evidence base),
   `anvil/revamp/ops/RUNBOOK.md`, the latest Gate-0 artifact `anvil/reports/gate0_62d/gate0.{md,json}`,
   and the trackers `next_wave.md` / `future_waves_of_upgrade.md`.
2. **Gate-bound. Do NOT ship anything actionable, sized, or "edge-verified" until the gate certifies it.**
   The order is: harden the gate → calibrate → **certify (Gate-0)** → only then size/emit. Do **not**
   build the live sized-tips money path (Wave 6 / P5) until `gate0_passed()` flips True *honestly*.
3. **Surgical, not a rewrite.** The ~80% engine spine is correct and validated (Black-76 on the futures
   forward, Breeden-Litzenberger RND, GEX, the CPCV/DSR/PBO/Harvey-t battery, calibration, the
   source-class firewall, the personal-mode wall). **Do not rewrite the engine. Do not change the
   statistical formulas** in `backtest/validation.py`, `backtest/aggregate.py::validate_cells`,
   `backtest/gate0.py`, or `calibration/conformal.py` — fix the *inputs* they're fed. **Do not add deep
   nets** (trees/GBM beat them on tabular after costs at these horizons, per the research report; the
   door is open only for a future intraday L2/LOB model that beats GBM under CPCV).
4. **Every change is test-gated.** Test runner is **`./.venv/Scripts/python.exe -m pytest`** (Python 3.14
   venv; the host `python` lacks pytest/fastapi). Lint: **`./.venv/Scripts/python.exe -m ruff check anvil`**
   (keep it clean). The suite is large (~117 files / ~583 tests); two new untracked test files
   (`tests/test_stock_tips.py`, `tests/test_universe.py`) are already in the tree — fold them in. Keep
   it green. Add a regression test with every fix and every new signal.
5. **Be adversarial about your own conclusions.** For breadth (auditing many modules, verifying many
   claims, evaluating many surfaces), fan out parallel subagents / a workflow and **adversarially
   verify** findings (independent skeptics, "try to refute this edge"), exactly as the gate does to
   signals. A finding that survives refutation is worth more than three that don't.
6. **Report before anything irreversible.** After the evaluation (Phase A) and the plan (Phase B),
   **stop and present** before you touch sizing, the wall, the gate inputs, git history, `.env`, or the
   running server.

---

## 2. Runtime ground truth & gotchas (verify these first — they bite)

- **Layout:** product repo = `anvil/` (a git repo, branch `master`). Its parent `Stock Market App/`
  holds sibling docs, the `realtime_sim/` standalone VRP sim, and *stale duplicate* `*.duckdb` /
  `anvil_app.db` copies (ignore the parent copies; the live ones are inside `anvil/`).
- **Durability is now LARGELY RESOLVED — verify, then keep it that way.** Git HEAD is a single
  **`Initial import: Anvil options-intelligence platform + tooling`** commit that *does* track the
  previously-untracked subsystem (`gating.py`, `tips/`, `factors/`, routers, the test suite). As of this
  writing the working tree has **~11 modified + 2 untracked files** — the *in-flight bug fixes* (see §7):
  `api/app.py`, `api/routers/{tips,momentum}.py`, `backtest/{data,tip_backtest}.py`, `cli.py`, `config.py`,
  `db/engine.py`, `tips/predict.py`, `web/src/{App.tsx,api.ts}`, plus `tests/test_{stock_tips,universe}.py`.
  **Commit the known-good tree early** (secrets/DBs excluded) so a filesystem event can't lose the fixes.
  `realtime_sim/` is still *outside* the git repo and has been truncated before — put it under version
  control too, with a `py_compile` check. **(This is the item most changed since v1 — the tree is no
  longer "entirely uncommitted." Re-verify with `git status` and don't re-report the old risk as current.)**
- **Secrets — still flag and remediate.** `.env` is correctly **gitignored** (verify with
  `git check-ignore anvil/.env`). But live, unredacted Upstox + Groww keys live in the working-tree
  `.env`, and secrets were present in the tree *before* the initial import. **Tell the owner to rotate
  any previously-exposed Upstox API secret + Groww credentials on the provider side** (you cannot rotate
  them). Delete `.env.example.bak` if present; confirm `.env.example` holds placeholders only.
- **The app is (likely still) RUNNING live.** A `anvil go-live --force-open` process serves the API +
  SPA on **http://localhost:8000** against **real Upstox** market data (`/health` → 200;
  `/api/source/status` → mode=live, source=upstox). Confirm with `GET /health` and a process check before
  assuming anything. There may be **zombie/duplicate go-live launchers** — reconcile to a single instance.
- **DuckDB is single-writer — this is the #1 recurring operational trap.** The running server holds a
  write lock on `anvil_store.duckdb` / `anvil_ledger.duckdb`. A second writer (a backtest, the recorder,
  a second `go-live`) raises `IOException: ... being used by another process`, and even `read_only=True`
  can fail while the server holds it. **`anvil cert full` / `anvil gate0` are safe alongside** because
  they write *separate* `anvil_cert*.duckdb` files. Run any new backtest/cert to a temp
  `--store-path`/`--ledger-path`. Never assume you can open the live store.
- **Do NOT blindly run the full suite or a full cert during evaluation.** A 62-day option+equity
  backtest is **~20–30 min** (per-chain Breeden-Litzenberger ≈1.3s; NIFTY stacks ~18 expiries/day). A
  full-depth cert is far longer. Scope your runs; use `--max-expiries 2`, windowed caches, the streaming
  `BhavcopyArchive.iter_days` loader, and `ProcessPoolExecutor` paths.
- **Live-data reality (account-level, not code):** Upstox is the working local live path (pure httpx; a
  browser User-Agent is required or Cloudflare 403s; the owner's token is a 1-year extended token, exp
  2027). **Groww cannot go live locally** (`growwapi` needs Python ≤3.13; venv is 3.14) and additionally
  needs a paid market-data role. Don't re-derive these as bugs.

---

## 3. What Anvil is (the system you're evaluating)

A **calibration-first options-intelligence PWA**: React/Vite SPA over a FastAPI backend, with a
pure-numpy, pandas-free quant engine and a DuckDB calibration moat. Single personal owner,
multi-user-ready schema, auth-gated, **flat-free, paper + analytics only**. The thesis: the Indian
options-tips market runs on uncheckable "90% accuracy" claims; Anvil instead sells **calibrated
probabilities on a live, public, auditable reliability curve** — the one thing a competitor can't copy
because it only accrues over calendar time.

**Architecture (tiers — confirm against the tree):**

| Tier | Path | Role |
|---|---|---|
| **engine/** | `anvil/anvil/engine/` | Pure-numpy primitives: `greeks` (Black-76 on the forward), `implied_dist` (Breeden-Litzenberger RND), `gex`, `regime`/`regime_score`, `iv_crush`, `event_risk`, `montecarlo`, `scenarios`, `participant_oi`, `higher_order` (vanna/charm/vomma); W2: `touch_probability`, `realized_vol_forecast` (VRP), `term_structure`, `decision_brief`; Wave-I: `momentum`, `flow_momentum`, `dealer_flow`, `chain_dynamics`, `constituents`. |
| **factors/** | `anvil/anvil/factors/` | Regime-gated `@register` `FactorSignal`s (index_options, equities, events, regime_gate; Wave-I momentum/dealer_flow/chain_analytics — display-only). |
| **strategy/** | `anvil/anvil/strategy/` | `SignalContext` (compute analytics once), `library`, `generate` (conviction/EV/decision policy), `sizing` (fractional Kelly + edge-shrink/CVaR/margin/short-vol caps), `tail`. |
| **tips/** | `anvil/anvil/tips/` | Public tip/prediction surface: `predict` (never-empty), `pipeline`, `gate`, `equities`, `eod`/`intraday`, `resolve`, `calibration`, `trust_dial`, `store`; Wave-I fusion: `meta_label`, `meta_features`, `ensemble`, `momentum`, `series`. |
| **backtest/** | `anvil/anvil/backtest/` | Anti-overfit moat: `validation` (CPCV/embargo, DSR, PBO, Harvey-t), `aggregate::validate_cells`, `gate0`, `gate_report`, `tip_backtest`, `full_cert`, `vrp_prior`, `orthogonality`, `robustness`, `trials`, `data::BhavcopyArchive`, `asof`, `horizon`. |
| **calibration/** | `anvil/anvil/calibration/` | `isotonic` (PAV+Platt+identity), `crossval` (OOF ECE), `conformal` (abstain τ, Mondrian, ACI, `risk_coverage_threshold`, `ev_coverage_threshold`), `combine` (Ledoit-Wolf ZCA whitening), `service`/`store`. |
| **ledger/** | `anvil/anvil/ledger/` | `CalibrationLedger` (DuckDB forecasts/outcomes), `scoring` (Brier/ECE/reliability), source-class firewall. |
| **live/** | `anvil/anvil/live/` | `supervisor::LiveSupervisor` (one-process cockpit), `cycle`/`daily` (moat clock), `recorder`/`recorder_loop`, `closes`, `clock` (`is_market_open`), `live_runner`, `bar_aggregator`, `trading_calendar`, `eventbus`. |
| **ingest/** | `anvil/anvil/ingest/` | `source::pick_connector` (token-aware demo↔live), `upstox`/`groww`/`dhan`/`kite`, `bhavcopy`/`backfill`, `instruments`, `yahoo`, `candle_cache`, `positioning`/`nse_eod`. |
| **paper/, ledger/, db/, auth/, agent/, store/, execution/** | … | Paper loop (costs/margin/governor/mtm); product OLTP (SQLAlchemy async + SQLite/Postgres); auth (argon2id, sessions, Fernet broker tokens, `require_personal_owner`); grounded LLM `analyst` + compliance `guardrail`; `SnapshotStore`/`BarStore`; gated `OrderGateway` (auto-exec OFF). |
| **gating.py / config.py / cli.py** | `anvil/anvil/` | Emission interlock (`gate0_passed`/`personal_mode_armed`), feature flags, the `anvil` CLI. |
| **web/** | `anvil/web/src/` | React PWA: tabs `today · tips · momentum · sim · risk · copilot · alerts · more`; `charts.tsx`, `api.ts`, `simStore.ts`. |

**Storage:** DuckDB = analytics/quant + calibration moat (`anvil_store.duckdb` snapshots/chain_rows +
tip validation/coverage/calibrators; `anvil_ledger.duckdb` forecasts/outcomes; `anvil_bars.duckdb`
OHLCV; cert artifacts in separate `anvil_cert*.duckdb`). **SQLite/Postgres** = product OLTP
(`anvil_app.db`: users, sessions, broker tokens, watchlists, paper runs). **The moat = the validation
harness + the calibration ledger + the source-class firewall.** Any new signal must clear the *same*
gate, on its own ledger class, before it may headline.

---

## 4. The goal, precisely — and the definition of "done"

Restate of §0 with the acceptance bar. The owner approved this verbatim framing (innovation is priority
#1): *"push selective-prediction accuracy above 75% across all surfaces and all horizons … honestly —
never by overfitting and never with fake overconfidence … monetization = maximum operator trading P&L,
not SaaS."*

**The four honest levers for raising accuracy (use these, not loosened gates):**
(i) more *genuinely orthogonal* edge sources agreeing; (ii) regime-conditioning; (iii) **meta-labeling**
(calibrated ACT/ABSTAIN — raises precision on taken trades without predicting direction); (iv)
**conformal coverage control** (lower coverage → higher accuracy, with a distribution-free guarantee).
A fifth, money-specific lever is already wired and should drive the operating point: **EV-at-coverage**
(`calibration/conformal.py::ev_coverage_threshold`) — set τ on the EV × coverage frontier, because
accuracy alone isn't P&L.

**Definition of done (per the plan's own success criteria — hold yourself to these):**
- `">75%-when-it-speaks"` is **reported per surface × horizon as a MEASURED accuracy-at-coverage point,
  never asserted.** The reliability curve stays **near-diagonal** (stated p ≈ realized) per surface ×
  horizon, with **disclosed coverage**.
- A **planted redundant OR overfit signal is REJECTED** by the orthogonality + DSR/PBO/Harvey-t battery
  (required regression tests — `test_orthogonality_admission`, the Gate-0 overfit-rejection test).
- **`gate0_passed()` flips True honestly** (Wave 5): the conviction cell and/or new uncorrelated cells
  clear **t ≥ 3 + the full battery** on full-depth data, **with no formula change**, and the live
  **trust dial** publishes the measured reliability curve.
- With cert passed **and** `ANVIL_PERSONAL_MODE=1`, the live **paper** loop issues sized, governed,
  abstaining tips across **all four universes**, publishes live P&L + the reliability curve, **and stays
  fully walled when not armed** (public surface carries no sized/actionable output).

**Gate-0 pass bar (verbatim — do not soften it):** *at least one target sustains **≥ ~65% calibrated
accuracy at ≥ ~10–15% coverage** with **DSR ≥ 0.95, PBO ≤ 0.5, Harvey t ≥ 3, trials counted**, plus
n ≥ 50 independent days, calibration ≥ conviction, post-cost edge > 0, bootstrap 5th-pct > 0.* Report
per-target accuracy–coverage AND EV–coverage curves. (Note: ">75% when it speaks" is the *ambition*;
~65%@~12% is the *minimum certifiable bar*. Both are honest because both are measured at disclosed
coverage.)

---

## 5. Non-negotiable guardrails (violating any of these fails the task)

- **G1 — Measured, never asserted.** Accuracy comes from a cell clearing the full battery, shown on the
  live reliability curve. An empty headline is the honest default — the engine stays quiet rather than
  manufacture a call. Enforced by `tests/test_docs_honesty.py`, `test_backtest_guards.py`,
  `test_source_separation.py`. Keep them green; extend them.
- **G2 — No monetization. Ever. Do not raise it.** No subscriptions/tiers/paywalls/affiliate/billing —
  not in code, plans, UI, or passing. `tips_enabled`/`paper_trading` are pure on/off flags, never tier
  gates. "Monetization" = operator trading P&L only. *(The old `docs/PITCH.md` still contains stale
  subscription/execution-tier language — treat that as a doc bug to fix, not a goal.)*
- **G3 — Keep the "high accuracy" brand, and make it true.** Don't re-litigate the headline; substantiate
  it with calibration + the conditional "~62–68% (stretch 70–80%/>75%) when it speaks, on disclosed
  coverage" framing. Flag the SEBI line once (below), then proceed.
- **G4 — Read-only market data.** Broker connections read positions/chains only.
- **G5 — No real execution.** `TRADING_AUTOMATION` / `trading_automation` stays OFF; execution stays
  dry-run/assisted. **Never place an order, move money, or wire live execution.**
- **G6 — No gate circularity (four binding overrides).** Calibrated conviction must **not** enter the
  gate's certification (the gate tests RAW native confidence); calibration-quality numbers (ECE
  before/after) must be **out-of-fold**; ship interfaces that degrade to identity; **sizing math runs on
  RAW edge** — calibrated prob is display/threshold only. Keep a raw fallback at every consumption point.
- **G7 — SEBI / compliance lane.** Analytics & education with calibrated probabilities; no specific
  buy/sell/target/sized language on any *public* surface (that lives behind the `PERSONAL_MODE` owner
  wall, ADR 0006). Flag once: *"get a SEBI Research-Analyst / securities-lawyer sign-off before any
  public accuracy marketing or order automation,"* then continue building behind the wall.
- **G8 — Keep `anvil/docs/ANVIL.md` current** on every substantive change (it's the canonical
  state/record; distinct from `next_wave.md` = next task and `future_waves_of_upgrade.md` = backlog).
- **G9 — Trust the code, not `anvil/reference/`** (older snapshots). Pandas-free pure-numpy; Black-76 on
  the futures forward, never BSM-on-spot.

---

## 6. Where the build stands & the gate-bound roadmap

**Shipped (verify, don't re-derive):** the engine spine; the anti-overfit battery (CPCV/embargo, DSR,
PBO, Harvey-t, day-blocked independent-n, honest `n_trials`); the calibration layer (PAV isotonic +
Platt + conformal, wired *display-only* so it never games the gate); the source-class firewall; honest
sizing + per-ticket risk distribution; the **personal-mode hard wall** (ADR 0006); the live loop + moat
clock + always-on recorder; the one-process cockpit (`go-live`); the Decision-Brief engine; never-empty
predictions; the 24-month bhavcopy backfill (**624 days**); the streaming `BhavcopyArchive.iter_days`
loader (the OOM fix); the cert-resolution-cap fix. Master-plan Phases **P0–P6 are logged shipped**, and
innovation **Wave I engines (momentum/flow/dealer-flow/orthogonality), Waves 1–2, Wave 0 backend** are
in the tree. **Phase 3 / Gate-0 is now BUILT and has been RUN once** — `backtest/gate0.py` +
`gate_report.py` + `anvil gate0` exist, and the 62-day dry-run artifact is at
`anvil/reports/gate0_62d/gate0.{md,json}`.

**The Gate-0 reality, as actually measured (re-verify the JSON):**

| target / source | n | coverage | cal. accuracy | EV | DSR | PBO | Harvey t | binding constraint | verdict |
|---|--:|--:|--:|--:|--:|--:|--:|---|:--:|
| conviction/tip_backtest | 212 | 85.8% | **74.8%** | +0.377 | 0.975 ✓ | 0.371 ✓ | **2.636 ✗** | **Harvey-t only** (needs ≥ 3) | abstain |
| equity/tip_backtest | 440 | 0.0% | — | — | — | — | — | **no positive edge / 0 coverage** | abstain |

Global verdict: **⛔ NO-GO / ABSTAIN** — correct and honest on this depth. **The two cells fail for
*different* reasons, and that distinction is the whole story:** conviction is one orthogonal cell and ~38
more independent days away from certifying (depth alone likely lights it); equity needs a *better signal*
(cross-sectional ranking, §I.3), not more of the same. **Do not over-promise that depth alone lights
everything.**

**The innovation plan you are completing (Wave I + Waves 0–6):**
- **Wave I — the innovation engine (priority #1).** Nine gate-certified signal families: **I.1**
  dealer-flow microstructure (vanna/charm/gamma hedging flow; Baltussen last-30-min, re-validated on
  Indian data); **I.2** promote the VRP harvesting prior (measured 65.2% win / ≈+16%/yr / Sharpe 1.89 on
  `backtest/vrp_prior.py`) from prior → certified cell; **I.3** cross-sectional → index aggregation
  (predict ~5 heavyweight BankNifty constituents ≈82% weight + Nifty top names → aggregate → exploit
  stock→index lead-lag; the research report's #1 novel angle — **and the most promising fix for the dead
  equity cell**); **I.4** decorrelated ensemble + López-de-Prado meta-labeling (ZCA-whitened inputs,
  OOF-only — **"THE honest >75%-when-it-speaks mechanism"**, currently built but display-only /
  cold-start abstain); **I.5** regime-switching trust gate (CUSUM + rules); **I.6** time-series conformal
  selective layer (ACI per surface×horizon); **I.7** intraday order-flow imbalance
  (Cont-Kukanov-Stoikov OFI from Upstox L2; abstain if no depth); **I.8** the information-theoretic
  orthogonality + Bayesian-shrinkage **admission gate** (the formal guard against overfitting/false
  confidence — a new signal is admitted only if it adds incremental OOF edge AND is decorrelated);
  **I.9** the AI research loop (LLM proposes features → sandboxed code-gen → the existing gate is the
  adversary → only measured-edge promoted).
- **Waves 0–6 serve Wave I:** **0** unify into one cockpit; **1** candle/bar data layer; **2**
  multi-timeframe momentum (the headline ask); **3** chain-dynamics analytics (gamma-flip S/R, skew
  slope, max-pain dynamics, 0DTE, OI velocity, vanna/charm aggregator, smart-money blocks); **4**
  single-stock options + equity parity (all four universes); **5 — the hinge — CERTIFICATION IN DEPTH**
  (raise independent-day n on the 626-day cache via streaming loader + content-hash RND/GEX cache +
  ProcessPool, add uncorrelated cells, flip `gate0_passed` True, **no formula change**); **6**
  paper-trade-live (last, only after cert + personal mode).

**The single hinge:** almost everything actionable waits on **Wave 5 / Gate-0 full-depth re-cert**. The
Gate-0 *plumbing* now works (the 62-day dry-run proves the pipeline end-to-end); what's missing is
**depth** — run the same `anvil gate0` against the full 624-day backfill (to a temp store), which raises
independent-day n and should push the conviction cell's Harvey-t over 3. The wall auto-arms the moment a
cell certifies (no code change) — *if* `ANVIL_PERSONAL_MODE=1`. So the highest-leverage sequence is:
build the per-chain RND/GEX cache (R5) → run full-depth cert tractably → add ≥1 uncorrelated cell →
light the gate → then (and only then) open the money path.

---

## 7. Current & recurring problems you must evaluate and fix

These were verified against the live code and the owner's **2026-06-23 screenshots**. Confirm each
yourself, then fix **without loosening any rail.** Several are *honest-but-degenerate display values* or
*correct fail-closed behavior surfaced confusingly* — the fix is usually presentation/wiring/shrinkage,
**not** the engine. Files `api/routers/tips.py`, `tips/predict.py`, `web/src/App.tsx`, `web/src/api.ts`
are **already modified in the working tree** — an earlier session started these fixes; finish, test, and
commit them rather than starting over.

**Live UI bugs (confirmed on screen 2026-06-23):**

1. **"Couldn't load tips."** on the Tips-tab live-prediction panel. Root cause: `api/routers/tips.py`
   fetches the chain (`get_source`/`get_chain`/`attach_parity_forward`) and runs `predict_for_chain`
   **unguarded**, so any live-source/chain/predict exception 500s the endpoint; and `web/src/App.tsx`
   maps **only 403** to a specific message, collapsing 401/404/500/network into one generic string.
   **Fix:** guard the chain-fetch + prediction so a source failure returns a typed "source unavailable"
   payload; surface the real status in the UI (401→"log in", 5xx→"engine/source error"). *(Partial fix
   may already be in the modified `tips.py`/`App.tsx` — verify it covers all status classes.)*

2. **Every single-stock BUY/SELL tip shows an identical 62.0%.** Not a literal constant — a *saturating
   prior*: `tips/equities.py` `edge_prob = min(cap, 0.5 + 0.12·min(1,|score|))` with `cap = 0.62`
   (`config.py`), and `conviction = edge_prob`. The surfaced names are the highest-|score|, so they all
   hit the 0.62 ceiling. **And it's an honesty problem:** the pooled EQUITY cell has *no positive
   measured edge* (Gate-0: 0% coverage), so a 62% bullish-confidence is not defensible. **Fix:** spread
   the prior across surfaced names by *relative* cross-sectional rank/z-score (not `min(1,|score|)`),
   and/or display the *calibrated* conviction (or an honest "no measured edge" state) instead of the raw
   saturated prior. The durable fix is **I.3 cross-sectional ranking**.

3. **Near-100% confidence chips ("99% tracking", "P(rich) 99.9%").** Both are real outputs of edge-case
   math shown raw. (3a) When no tip clears the gate, `tips/predict.py` falls back to a raw RND
   probability (`prob_above`/`prob_between`), which → ~0.99 on a tight/near-expiry chain (a weekly-expiry
   day); the "tracking" badge literally means "edge NOT verified." (3b)
   `engine/realized_vol_forecast.py` computes `P(rich)=Φ(z)` with `sd` floored at 0.05 — too tight — so
   the Gaussian tail pins at 0.999. **Fix:** when `edge_verified=False`, cap/shrink the *displayed*
   confidence (show calibrated_confidence or a "no measured edge" state, not a raw 99% RND prob);
   widen/regularize the `log_rv_std` floor; show P(rich) in coarse rich/fair/cheap buckets rather than a
   99.9% point estimate. **This is the bug most corrosive to the brand — prioritize it.** *(`predict.py`
   is in the modified set — verify the shrink actually fires on the `edge_verified=False` path.)*

4. **Stock tips stale ("as of 2025-11-28" on a live 2026 session).** `api/routers/tips.py` serves the
   last persisted issued tip from `IssuedTipStore` (`as_of = created_ts = the bhavcopy EOD date`); the
   live "moat clock" `live/daily.py` is **index-only** and never calls `run_equity_tip_cycle`, and the
   bhavcopy archive isn't being refreshed. **Fix:** wire `run_equity_tip_cycle` into the supervisor's
   nightly job (and refresh the archive), or recompute equity tips on read; show a "stale" badge when
   `as_of` is older than N days.

5. **Track record 0 / gate chip dark.** This is **correct fail-closed behavior**, not a bug: `gating.py`
   requires a cell with `headline_eligible AND t ≥ 3` **and** `personal_mode`, and the cert evidence
   lives in separate `anvil_cert*.duckdb` files, not the serving ledger. **Do not "fix" by loosening the
   gate.** To light it honestly: pass the full battery on depth, merge headline-eligible cells into the
   *serving* store, run the live resolve loop so `tip_live` rows accrue, and set `ANVIL_PERSONAL_MODE=1`.

**NEW bugs confirmed in the 2026-06-23 deep-read (not in v1 — add to triage):**

6. **Stale-EOD data wears a `LIVE` badge (labeling bug — high brand risk).** `is_market_open()` exists
   (`anvil/live/clock.py`, returns False on weekends/after-hours) but **only gates the background paper
   runner + CLI — the web read path (`api/routers/tips.py`) never calls it.** With
   `ANVIL_PRIMARY_SOURCE=upstox` + a valid token, loading the page over a weekend hits Upstox's REST
   chain endpoint, which returns **Friday's frozen EOD** (LTP/OI/IV + last cash spot). The chain is then
   stamped `datetime.now()` (`ingest/upstox.py`) and `data_mode()` (`engine/provenance.py`) labels any
   non-demo source `LIVE` — so two-day-old closing data shows as `LIVE · as of Sat …`. **Fix:** call
   `is_market_open()` on the web read path; when closed/stale, label it **"last close (DD-MM)"** with a
   staleness badge, never bare `LIVE`. (Honesty rail G1 — a misleading freshness label is the same class
   of sin as a misleading accuracy number.)

7. **`MAX LOSS` understates the true tail on naked structures (risk-honesty bug).** The short-strangle
   card shows `MAX LOSS = 2.5 × credit` (`strategy/library.py` ~:246–247) — a *modeled stop*, not a real
   floor — e.g. ~₹46.7k against ~₹18.7k credit, while the card's own payoff chart plots a true
   held-to-horizon min of ~**−₹18.4 lakh** (the structure is tagged `naked: True`). A weekend gap blows
   straight through a 2.5×-credit stop. **Fix:** display the **CVaR-based true tail** (or the plotted
   held-to-horizon min) as `MAX LOSS` for naked/undefined-risk structures, with the stop shown
   separately as "modeled stop (not guaranteed)." Defined-risk structures (iron condor = width − credit)
   are fine. This overlaps the Wave-4/P4 sizing item ("make naked `max_loss` a CVaR-based true tail") —
   but the **display** half is shippable now, behind tests, without touching sizing.

**Recurring / structural problems (across many sessions — design for them, don't just patch):**
- **R1 — DuckDB single-writer lock.** Recurs by design. Enforce a single-instance rule for
  `go-live`/`record`; keep cert on its own store; consider a write-broker/queue or WAL strategy if
  multi-writer is ever needed.
- **R2 — "won't flip to live / stuck on DEMO."** Fixed repeatedly (token-aware `pick_connector`, cascade
  in `cached_analyze`, `.env` autoload). Verify the resolver still cascades and surfaces the real reason;
  remember Groww-local and account-level gating are *not* code bugs.
- **R3 — stale service worker / "old tab-less build."** Fixed by removing vite-plugin-pwa + a `/sw.js`
  kill-switch; the deeper trap was *deploy staleness* (a fix in source but an old running image). Guard
  against serving a stale bundle; verify the served hash matches the source build.
- **R4 — Gate-0 can't certify (Harvey-t / independent days).** The central blocker — Wave 5. **Not a
  defect; the gate working** (the 62-day report proves the pipeline runs and abstains honestly). Close it
  with depth + uncorrelated cells, never by softening the bar.
- **R5 — slow backtests / engine perf.** Per-chain RND ≈1.3s. The per-chain **RND/GEX content-hash
  cache** is still TODO — build it; it's the unlock for tractable full-depth cert.
- **R6 — local-dev traps:** stale `*.duckdb` schemas (BinderException → `rm *.duckdb`); frozen-`Settings`
  dataclass (`object.__setattr__`); NaN→500 (`json_safe`); tab-reset (keep-alive tabs + `simStore`).
  Mostly fixed — keep regression coverage so they don't return.
- **R7 — overclaiming.** Audits keep catching inflated test counts / optimistic claims. Honesty-lint
  exists because claims need *enforcement*, not assertion. Hold every number you report to the same
  standard. **(This v2 itself corrected a stale claim from v1 — the "entirely uncommitted tree" — by
  re-checking `git status`. Do the same with every number here.)**
- **R8 — autonomous-execution friction (the meta-problem; see §8).** Past sessions stalled not on code
  but on *driving* the build: screen capture drops when the display sleeps, VS Code is typing-blocked,
  long runs "get stuck," and the human had to shuttle prompts paste-by-paste. The fix is to make
  execution **self-driving and checkpointed** (next section), not to depend on flaky screen control.

**Built-but-not-finished worth resurfacing:** the I.3/I.4 fusion layer (display-only, cold-starts to
abstain until resolved history accrues); the `realtime_sim` → anvil migration (staged:
`migrate_tips_v2.py --commit` → `ledger run-daily --full` → review → delete `realtime_sim/`); broker
WebSocket feeds (only REST-poll built); real Groww margin API (SPAN-lite today); validating the GEX
dealer-sign convention on real data; the AI research loop (I.9).

---

## 8. Autonomous-execution + verification playbook (run the phases hands-off)

The owner wants **"perfect execution of all remaining phases, hands-off, with 100% context maintained."**
Past sessions proved the bottleneck is *operational*, not intellectual. Follow this so the build runs
itself and never silently stalls.

**8.1 Be self-driving — don't depend on screen control.** You are running *inside* Claude Code with
direct file + shell + test access. **Do the work directly with your own tools** (read/edit files, run
`pytest`, run `anvil` CLI) — do **not** route edits through desktop screen-capture/clicking, which is the
exact channel that dropped out before (display sleep → blank capture; VS Code blocks typing). If you
ever find yourself trying to "paste into a box," stop: you have the editor.

**8.2 Phase loop (repeat per phase, P3-residuals → P4 → P5 → P6, gate-bound):**
1. **Plan** the phase from `revamp/Anvil_Master_Build_Plan_v3.md` (+ build-on-it for the monetization
   goal). State the files, the new regression test, and the acceptance check *before* editing.
2. **Baseline-green gate:** run the *focused* test subset for the area first; confirm green before any
   edit. Never build on a red baseline.
3. **Implement** surgically; add the regression test in the same change; keep ruff clean.
4. **Verify:** re-run the focused subset (not the slow full cert). For breadth, spawn an adversarial
   subagent to try to refute the change.
5. **Checkpoint:** update `docs/ANVIL.md`, commit the known-good tree (secrets/DBs excluded), and write a
   one-line status to the phase log. **Stop and report at each phase boundary** and before anything
   irreversible (sizing, the wall, gate inputs, `.env`, git history, the running server).

**8.3 Don't get "stuck" — scope every long job and background it.**
- A full-depth cert / 624-day backtest is tens of minutes to hours. **Never run it inline and wait.**
  Launch it to a **temp store** (`--store-path /tmp/cert_*.duckdb`) **in the background**, write a
  **progress/checkpoint line to a log file**, and poll the log — don't block the turn on it. The backfill
  is resume-safe (`_is_cached`); a killed run continues.
- Keep heavy runs **off the live DuckDB** (R1). The server holds the write lock; `anvil gate0` / `cert
  full` use separate `anvil_cert*.duckdb`, so they're safe alongside — but a second `go-live`/recorder is
  not. Reconcile to **one** `go-live` instance.
- If a step needs the live server's data, **read via the API** (`/health`, `/api/...`), don't open the
  locked store.

**8.4 Maintain 100% context across phases.** Treat `docs/ANVIL.md` + `next_wave.md` +
`reports/gate0_*/` as the durable memory between phases (not your chat scrollback). After each phase,
write what shipped, what the tests prove, and the exact next action there — so any fresh session
(or a resumed one) can pick up without re-deriving. Convert relative dates to absolute.

**8.5 Per-phase acceptance gates (the only definition of "done"):**
- **P3 residuals** — `embargo = label horizon` threaded into OPTIONS (`backtest/tip_backtest.py`) and
  LIVE (`backtest/revalidate.py`) cert paths (EQUITY already does it); CPCV
  (`combinatorial_purged_splits`) wired into `validate_cells` *or* a documented walk-forward-only
  decision; regression test proves an in-loop threshold sweep **raises** the DSR bar and **rejects** a
  planted overfit cell. Re-run `anvil gate0` on 62 days → same honest NO-GO, now with embargo+CPCV.
- **R5 perf** — per-chain content-hash RND/GEX cache lands; a windowed cert that took N min drops
  measurably; correctness test proves cached == uncached outputs.
- **Wave 5 cert (the hinge)** — full-depth `anvil gate0` to a temp store; **report per-target
  accuracy/EV-vs-coverage**; if the conviction cell clears **t ≥ 3 + full battery with no formula
  change**, merge the headline-eligible cell into the serving store and confirm `gate0_passed()` flips
  True *honestly*. If it still abstains, that's a valid outcome — report it, don't tune toward green.
- **Display-honesty fixes (bugs 1–4, 6, 7)** — shippable now, behind tests, **without touching the
  gate** — each with a regression test asserting the misleading value can't reappear (no raw 99% when
  `edge_verified=False`; no `LIVE` badge when `is_market_open()` is False; naked `MAX LOSS` = CVaR tail).
- **P4 sizing / P5 live loop / P6 paper-live** — **gate-blocked.** Do **not** build until
  `gate0_passed()` is honestly True. When it is: edge-uncertainty shrink + CVaR cap + cost-adjusted EV +
  margin-feasibility cap in `strategy/sizing.py`; the distribution on every ticket
  (`engine.montecarlo.mc_pnl`); the `PERSONAL_MODE` wall verified fail-closed on every public surface +
  SSE.

---

## 9. What I want you to produce (your deliverables, in order)

### Phase A — The Evaluation Report (`anvil/docs/EVALUATION_2026-06-23.md`)
A rigorous, evidence-cited audit. No vibes — every claim carries a `file:line` or a measured number you
re-verified. Cover:
1. **State vs goal gap analysis** — for each of the four surfaces × each horizon: what exists, what's
   measured, what's certified, what's missing. A matrix.
2. **The accuracy reality** — re-verify the conviction cell's numbers against `reports/gate0_62d/gate0.json`
   and, for *every* cert cell, its **actual binding constraint** (Harvey-t vs DSR vs PBO vs orthogonality
   vs negative edge). Reconcile "only n blocks it" honestly: it's true for conviction (Harvey-t only),
   **false** for equity (no edge — needs I.3). State what depth alone will and will not light.
3. **Honesty audit** — confirm the rails hold end-to-end: calibration never feeds the gate; source-class
   firewall intact; the personal-mode wall is fail-closed on every public surface and SSE; the docs (esp.
   the stale `PITCH.md`) match the enforced code. List every place a displayed number could mislead (the
   62% / 99% / `LIVE`-on-stale / `MAX LOSS` class of issue).
4. **Bug triage** — confirm/refute the §7 items (1–7) with root cause + a concrete fix, ranked by
   brand-damage × user-visibility × effort. Note which are already half-fixed in the modified tree.
5. **Innovation assessment** — for each Wave I family (I.1–I.9): is it built? wired? certified? what
   orthogonal edge does the research actually support (cite the report), and what's the realistic
   accuracy-at-coverage it can add? Be honest about likely dead ends (raw PCR/OI/max-pain as alpha) and
   the highest-value bet (I.3 cross-sectional → index, which also fixes the dead equity cell).
6. **Risk register** — durability (now mostly mitigated — confirm; the residual is the uncommitted
   in-flight fixes + `realtime_sim/` outside git + secret rotation), the DuckDB lock, deploy staleness,
   cert tractability, and the compliance/SEBI exposure of any actionable surface.

### Phase B — The gate-bound execution plan
A prioritized, sequenced plan that ties every item to the roadmap and the guardrails. Lead with the
**highest-leverage path to lighting the gate honestly** (R5 cache → tractable full-depth cert →
uncorrelated cells → flip `gate0_passed`), in parallel with the **brand-critical display-honesty fixes**
(bugs 1–4, 6, 7 — which don't touch the gate and can ship immediately behind tests). Mark what is
gate-blocked (sizing/Wave 6) and must wait. For each item: the change, the files, the new regression
test, and the acceptance check. **Present Phases A and B and stop for confirmation before any
irreversible change.**

### Phase C — Execute (after confirmation)
Implement in priority order using the §8 playbook — each change test-gated and ruff-clean, `ANVIL.md`
updated as you go, the working tree committed at each checkpoint. Use parallel subagents / a workflow for
independent work and adversarial verification. Re-run the relevant focused test set after each change
(not the slow full cert). Background the long cert/backfill jobs to a temp store and poll their logs.
Stop and report at each phase boundary and before touching sizing, the wall, the gate inputs, `.env`,
git history, or the running server.

---

## 10. What NOT to do
- Don't change the statistical formulas (PSR/DSR/PBO/Harvey-t/CPCV, `risk_coverage_threshold`,
  `ev_coverage_threshold`) — fix their inputs. Don't loosen the gate to make the chip light up. Don't add
  deep nets.
- Don't ship sized/actionable/buy-sell/target language on any public surface (PERSONAL_MODE wall only).
- Don't let calibrated probabilities enter the gate or the sizing math.
- Don't propose monetization, tiers, or paywalls in any form.
- Don't place orders, move money, or enable automated execution.
- Don't run the full cert or full suite blindly against the live DuckDB store, or start a second writer.
- Don't drive edits through desktop screen-capture/clicking — you have the editor and shell; use them.
- Don't trust this prompt's numbers without re-verifying them, and don't report a number you can't measure.

## 11. First actions
1. Read the canonical docs (§1) and the Gate-0 artifact, then **verify the live state** (`/health`,
   `/api/source/status`, `git status`, `git check-ignore anvil/.env`, ruff, `pytest --collect-only -q`)
   — don't run the slow suite/cert yet.
2. Confirm the durability + secrets posture: the tree is now committed (HEAD = "Initial import"); the
   residual risk is the **~11 modified + 2 untracked in-flight bug-fix files** and `realtime_sim/` being
   outside git. **Commit the known-good tree** (secrets/DBs excluded) and **tell the owner to rotate the
   previously-exposed Upstox/Groww secrets** before doing anything else.
3. Produce **Phase A (evaluation)** and **Phase B (plan)**, then **stop and report.** Begin Phase C only
   after the owner confirms the plan.

Keep abstention first-class, keep every claim measured, and remember the prize: **a small number of
genuinely high-accuracy calls, certified honestly, sized well — operator P&L earned without ever lying
about the odds.**
