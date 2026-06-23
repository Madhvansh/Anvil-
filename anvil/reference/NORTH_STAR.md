# North Star — Options Intelligence Platform

This is the mission and the rails. It is **deliberately not an implementation plan.**
You (Claude Code) own the architecture, the tech choices, the module design, and the
sequencing. Propose them — and propose capabilities we haven't listed if they serve the
mission better. We decide together at the plan gate.

## Mission
Build the options-intelligence platform for Indian markets (NSE/BSE) that wins on **trust,
not hype.** In a market full of tipsters claiming "accuracy," we prove *calibration*: every
forecast is a probability shown with its live, auditable track record. The platform also
gives a trader what no broker-locked tool does — a unified risk view across brokers, and an
AI analyst that reasons over their actual positions and live market data.

## Non-negotiable principles (hard rails — do not cross)
1. **Calibrated, not "accurate."** Forecasts are probabilities/distributions, never point
   targets with implied certainty. Calibration (Brier score, reliability diagram, band
   coverage) is computed on realized outcomes and shown alongside every forecast. No "high
   accuracy" or guaranteed-return claims anywhere in code, copy, or UI. Disclaimers on every
   forecast surface.
2. **Correctness is earned, not asserted.** Quant code is test-first; nothing merges without
   a passing check. The backtester's look-ahead and survivorship guards are tests that fail
   the build if violated.
3. **Data realities.** Greeks are computed locally with Black-76 (Indian options settle off
   futures); Kite Connect does not expose Greeks via API. Validate against broker-shown values.

Everything outside these three is yours to decide.

## Target capabilities (the "what," not the "how")
Outcomes the platform should reach. Design the implementation. **Challenge, merge, or extend
this list** — if you see a better capability, propose it.
- **Calibrated forecast engine** — probabilistic forecasts with a live calibration surface.
  This is the differentiator; treat it as the heart of the product.
- **Cross-broker unified risk book** — net Greeks + beta-weighted-to-Nifty exposure across
  Kite + Groww; portfolio scenario / Monte-Carlo P&L.
- **Event & regime intelligence** — event-aware (budget / RBI / earnings / expiry / F&O
  bans), regime-conditional forecasts, explicit IV-crush warnings.
- **Flow & positioning intelligence** — NSE participant-wise OI decoded into narratives; an
  unusual-options-activity scanner.
- **Analyst copilot** — natural-language interrogation of the live book + chain + models,
  grounded in real data.
- **Honest backtesting lab** — walk-forward, out-of-sample, cost/slippage-aware, bias-guarded.
- **Behavioral trade journal** — surfaces the user's own decision leaks.

Primary user is a **directional / buyer-leaning trader; optimize there first.** Seller-side
features are a later add-on.

## What "done" looks like (verifiable)
Define a concrete pass/fail check for every feature *before* building it. The bar:
- *Forecast:* a surface showing a probability and its current reliability curve; calibration
  recomputes as outcomes arrive.
- *Risk book:* net Greeks reconcile across both brokers and tie out to a hand-computed
  fixture within tolerance.
- *Backtester:* a known look-ahead violation makes the run fail, not warn.
End every feature spec with an end-to-end check that proves it works.

## Out of scope for v1 (prevent sprawl)
- Live order placement / auto-trading — analysis only to start.
- Brokers beyond Kite + Groww.
- Seller-specific modules — defer until the buyer path is solid.
Revisit anything here once the core holds.

## How we work
Explore → plan → implement → verify → commit. Plan non-trivial features in plan mode and
show me the plan before coding; I'll edit it at the gate. Interview me when a feature is
underspecified — dig into the hard parts I haven't considered. Verify your own work and show
the evidence. Surface tradeoffs and alternatives rather than guessing. A reference idea-bank
of earlier brainstorming may exist in the repo (e.g. an old spec) — you may draw from it,
but you are not bound by it.
