# ADR 0006 — Personal-mode hard wall (actionable/sized output is owner-only, Gate-0-gated)

**Date:** 2026-06-22 · **Status:** Accepted

## Context
ADR 0004 fixed the public stance as *analytics, not advice*: calibrated probabilities/ranges/regime
reads on a public reliability curve, never point buy/sell/target calls (issuing those triggers SEBI
Research-Analyst obligations). Phase 4 adds an **honest money layer** — sized tickets with the tail
shown (fractional-Kelly + edge-shrink + CVaR/margin caps, plus an mc_pnl risk map, risk-of-ruin and
forward-drawdown). That output is *inherently actionable and sized*, so it must not reach the public
surface. It is also only trustworthy once the edge is **certified** — and Gate-0 is a provisional
NO-GO (the conviction cell sits at Harvey t = 2.64 < 3.0 on the 62-day cache).

## Decision
- **Two surfaces, one engine.** The PUBLIC surface stays ADR-0004-clean: `Prediction.public_dict()`
  / `to_dict(owner=False)` (the fail-closed default) emits calibrated probabilities, ranges, regime
  read, factors and the reliability overlay — and **no** `actionable_tip`, sized legs, targets, ₹
  sizing, or position-level risk distribution. Actionable/sized output is **owner-only**.
- **One authority check.** `auth/deps.require_personal_owner` is the only gate: 403 unless
  `ANVIL_PERSONAL_MODE` is on **and** the caller is the single `owner`. Routers depend on it; they
  never re-implement it. The actionable tips live at `GET /api/tips/{u}/actionable`; the default
  `GET /api/tips/{u}` is public.
- **Default-closed + double-gated.** `ANVIL_PERSONAL_MODE` defaults **off** → the app is public
  analytics out of the box. The actionable PAYLOAD is additionally gated on `gating.gate0_passed()`
  (≥1 validation cell headline-eligible with Harvey t ≥ 3) via `gating.personal_mode_armed()`. So
  even the owner gets analytics-only until the edge is certified — "do not emit sized personal tips
  until Gate-0 passes" enforced as a RUNTIME invariant. The day the full-depth re-cert clears the
  gate, it flips live with no code change.
- **Serialization is the boundary; compliance is the backstop.** `to_dict(owner=…)` is the enforced
  projection (the same single code path for both views, so they can't drift); `agent.guardrail.
  check_compliance` stays the free-text scrub on every public string. The live runner's SSE egress
  applies the same `owner_view` gate (recording to the ledger stays full — that's internal
  measurement, not egress).
- **Not a tier.** Personal mode is owner utility, not a paid/feature tier — consistent with the
  flat-free, no-monetization stance.

## Consequences
- The public API can never emit a sized/actionable call, satisfying ADR 0004's compliance basis by
  construction (verified by the serializer-invariant tests, not by convention).
- Sized personal tips are silent until Gate-0 certifies real edge — the honest outcome on a book that
  hasn't accrued evidence, and the brake that stops a pretty backtest from short-circuiting the gate.
- Engage a SEBI securities lawyer before exposing the owner actionable surface beyond personal use.

## See also
- [`METHODOLOGY.md`](../METHODOLOGY.md) — how the public surface substantiates "accurate when it speaks"
  (calibration, coverage, the reliability curve) and where this wall sits in that story.
- ADR [0004](0004-calibration-first-compliance.md) — the analytics-not-advice basis this wall enforces
  by construction; ADR [0005](0005-bsm-on-spot-deferred.md) — sibling (pricing-scope honesty).
