# Options Intelligence Platform

Calibrated options-intelligence for Indian markets (NSE/BSE). Mission, rails, and
target capabilities live in @NORTH_STAR.md — read it before planning any feature.

## Non-negotiables (YOU MUST)
- Forecasts are PROBABILITIES shown with a live calibration score (Brier / reliability
  diagram) — never point targets or "accuracy" claims. Disclaimers on every forecast surface.
- Quant code (Greeks, risk math, backtester) is TEST-FIRST. Nothing merges without a
  check that passes.
- The backtester's look-ahead and survivorship guards are tests that FAIL the build when
  violated — not warnings.
- Greeks are computed locally with Black-76 (e.g. py_vollib); Kite Connect does NOT serve
  Greeks via API. Validate computed Greeks against broker-shown values for known strikes.

## Workflow
- Explore → plan → implement → verify → commit. For non-trivial work, plan in plan mode
  and show me the plan before coding.
- Always give yourself a runnable check (tests / build / script) and show the evidence —
  don't assert success.
- If a feature is underspecified, interview me (AskUserQuestion) before building. Don't
  guess on the hard parts.
- Architecture and stack are OPEN. Propose at the plan gate; record each accepted decision
  as a short dated note in docs/decisions/ (decision + why).

## Conventions
- Domain knowledge that's only sometimes relevant → a skill in .claude/skills/, not this file.
- Prefer a fresh, well-scoped session over a long, polluted one. Course-correction is welcome.

<!-- Keep this file short. For each line ask: would removing it cause real mistakes? If not, cut it. -->
