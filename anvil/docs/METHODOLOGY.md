# Trust & Methodology — how Anvil earns the word "accurate"

> **What this file is.** The single, plain-language account of *what Anvil claims, why those claims are
> defensible, and how you can audit them yourself.* It is the canonical source the in-product **Trust /
> Methodology** panel (More tab) condenses, and the substantiation behind the headline in
> [`ANVIL.md`](ANVIL.md) §1. If a marketing line and this file ever disagree, **this file wins** —
> the honesty spine is non-negotiable (ADR [`0004`](decisions/0004-calibration-first-compliance.md)).

---

## 1. "Accurate — when it speaks"

Anvil keeps the word *accurate*, but it is **conditional, not a headline**:

- **Raw, all-trades next-day index direction is ~50–55%, and Anvil does not claim otherwise.** The
  peer-reviewed evidence (and our own walk-forward) puts unconditional direction in the low-to-mid
  fifties; anything quoting an unconditional 70–80% directional hit-rate is almost always leakage,
  multiple-testing, or rule-recovery (see [`hypothesis.md`](hypothesis.md)).
- **What Anvil targets is selective accuracy on a small, disclosed subset.** On the **~10–20% of
  opportunities the engine is confident enough to call**, the honest target is **~62–68% (stretch
  70–80%)** — and on the other ~80–90% it **abstains**. Abstention is a first-class output, not a
  failure: the engine stays quiet rather than manufacture a call.
- **The proof is the reliability curve, not a number we assert.** "When we say 70%, does it happen
  ~70% of the time?" — measured across everything Anvil has ever forecast, shown live, and compressed
  to one intuitive **Calibration Score = `round(100 · (1 − ECE))`** (n ≥ 50 before any score shows).

The North-Star goal is **operator P&L**, earned by sizing the few high-conviction calls well — not by a
bigger accuracy headline. More calls is not better: correlated index strikes are not independent
breadth, and honest trial-counting *penalises* volume.

## 2. Measured, never asserted — the moat

Every "accuracy" number Anvil shows is computed from resolved outcomes on a ledger, behind these rails:

- **Source-class firewall.** Synthetic/demo/paper/seed data **never** blends into a public curve.
  Backtest, live, tip, and structural classes each live on their own firewalled curve; calibrators are
  keyed `(target, source_class)` so a backtest map can never drive a live prediction. (Enforced by
  tests, not convention.)
- **The gate ("Edge-verified ✓").** A cell may headline **only** after clearing the full anti-overfit
  battery: independent-**day**-blocked sample size, calibrated `win_rate ≥ conviction` on the engine's
  **raw** confidence, post-cost positive edge, **Deflated Sharpe ≥ 0.95**, **PBO ≤ 0.5**, **Harvey-Liu
  t ≥ 3**, and out-of-fold edge across **purged walk-forward + combinatorial (CPCV)** splits with
  `embargo ≥ the label horizon`. The decision threshold is chosen *inside* the walk-forward loop and
  **counted as a trial**, so the bar *rises* with researcher search (it cannot be tuned toward green).
- **Calibration is the honesty rail, never the gate.** Isotonic/Platt maps (out-of-fold, degrade to
  identity below sample size) drive **display fields and abstain thresholds only** — never sizing, and
  never the gate's `win_rate ≥ conviction` check (calibrating that input would make it pass by
  construction). See [`ANVIL.md`](ANVIL.md) §8.
- **Leak-safety.** Every backtest read goes through an as-of guard that raises on any look-ahead.

**Audit it yourself:** `GET /api/calibration` and `/api/ledger/report` (Calibration Score + reliability
curve, per class), `GET /api/tips/track-record` (per-cell verdicts), and the composed
`GET /api/tips/trust-dial` (Phase 5: reliability + accuracy-at-coverage + coverage % + the tail
scorecard + the gate status).

## 3. The money discipline — the tail is shown, not hidden

When (and only when) a sized ticket is produced, it is honest about risk:

- **Sizing survives, not maximises.** Fractional Kelly, **shrunk** for edge uncertainty, **capped** by a
  CVaR/tail budget and broker-margin feasibility, with a **hard 0.10 Kelly cap on short-volatility**
  structures (the negative-skew guard). Naked structures size against a **stress (≈3σ) tail**, not a
  modeled stop.
- **Distribution, not a point ₹.** Each ticket carries an mc_pnl risk map (percentiles, VaR/CVaR — a
  market-implied *risk map*, not a return forecast) plus **risk-of-ruin and a forward-drawdown
  distribution**. **Win-rate is never shown alone** — the tail block (maxDD, worst, CVaR5%, Calmar,
  Sortino) sits beside it.
- **The VRP-prior is a prior, not a track record.** The variance-risk-premium edge (selling India-VIX-
  priced premium vs. realised move) is shown as a clearly-labelled *prior* on a clean proxy — never as a
  live track record of Anvil's own structures, which accrue forward and must clear the same gate.

## 4. Two surfaces, one engine — the compliance lane

Anvil is **analytics & education, not investment advice** (ADR
[`0004`](decisions/0004-calibration-first-compliance.md)):

- **Public surface (the default).** Calibrated probabilities, ranges, regime reads, factors, and the
  reliability overlay — **no** point buy/sell/target calls, **no** sized legs, **no** position-level
  risk. The serializer (`Prediction.public_dict()`) enforces this by construction; a compliance scrub
  guards every free-text string.
- **Owner-only actionable surface (walled).** Sized, actionable tickets are owner-only behind
  `ANVIL_PERSONAL_MODE` + owner auth, and **double-gated on Gate-0** (ADR
  [`0006`](decisions/0006-personal-mode-hard-wall.md)): even the owner gets analytics-only until a
  validation cell certifies at Harvey t ≥ 3. The day the full-depth re-cert clears, it arms with **no
  code change**.
- **No monetisation.** Personal mode is owner utility, not a paid tier; every feature is flat-free.

## 5. Current honest state (as of 2026-06-23)

- **Gate-0 is a provisional NO-GO.** The `conviction` cell abstains on a *single* constraint —
  **Harvey t ≈ 2.64 < 3.0** (only ~12 independent days in the windowed cert) — while everything else
  clears (calibrated, DSR 0.975, PBO 0.37, accuracy 74.8%, coverage 85.8%, EV +0.38). The edge looks
  real but lacks **independent-day** evidence; full depth (624 days → ~120+ independent days) scales the
  t-stat ~3.2× and would clear the bar *if the edge holds*. This is honest discovery working as
  designed.
- **So the sized-tips wall is dark.** `personal_mode_armed()` is `False`; sized personal tips do not
  surface. The Trust panel shows this state truthfully (calibration "building" until n ≥ 50; the gate
  "not yet certified"). Substantiation is the goal here, not a certification that has not happened.

## 6. The one legal flag (stated once)

Marketing the word "accuracy" for securities can trigger **SEBI Research-Analyst** obligations.
Anvil's posture — calibrated probabilities + an auditable public reliability curve, with no point
buy/sell/target calls on the public surface — is built to be defensible, **but**: *engage a SEBI
securities lawyer before any accuracy-marketing copy ships, and before exposing the owner actionable
surface beyond personal use.*

---

*Related:* [`ANVIL.md`](ANVIL.md) (canonical state) · [`PITCH.md`](PITCH.md) (thesis) ·
[`hypothesis.md`](hypothesis.md) (research blueprint) · ADRs
[`0004`](decisions/0004-calibration-first-compliance.md) /
[`0006`](decisions/0006-personal-mode-hard-wall.md).
