# ADR 0004 — Calibration-first, analytics-not-advice (the compliance + moat spine)

**Date:** 2026-06-18 · **Status:** Accepted

## Context
"High-accuracy prediction" is unsellable honestly (out-of-sample directional accuracy ~50–55%) and
issuing buy/sell/target calls triggers SEBI Research-Analyst obligations. The durable, defensible
position is **calibrated probabilities with a public, auditable track record**.

## Decision
- All outputs are **probabilities / ranges / regime reads**, never point price calls.
- Build a **calibration ledger** (M3): every probabilistic forecast is logged with a timestamp and
  later scored against the realized outcome (Brier score, reliability diagram, band coverage). The
  reliability curve is the product's headline and its moat.
- Persistent **"analytics & education, not investment advice"** disclaimers on every surface;
  AI-use disclosed. The LLM agent (M5) is **strictly grounded** — every number from the engine, no
  freeform buy/sell/price output.
- Execution stays **assisted/gated** (auto-exec OFF) per the order-layer decision.

## Consequences
- "Accuracy" is *earned and shown*, not claimed — simultaneously the honest, the legally defensible,
  and the most differentiated stance.
- Engage a SEBI securities lawyer before any accuracy marketing or order automation.
