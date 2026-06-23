# ADR 0002 — Greeks: Black-76 on the futures price

**Date:** 2026-06-18 · **Status:** Accepted (supersedes Anvil's spot-BSM engine)

## Context
Indian index options (NIFTY/BANKNIFTY/…) are European and **settled off the futures**. The
original Anvil engine used Black-Scholes-Merton on **spot** with a fixed dividend yield and never
used the chain's `future_price` — systematically mispricing the underlying forward, with errors
that widen for OTM strikes, longer tenors, and when the basis is non-trivial. A product that
markets *calibrated* probabilities cannot be built on a mispriced engine.

## Decision
Adopt **Black-76 on the forward** (`anvil/engine/greeks.py`, grafted from OIP). The forward `F` is
a first-class input resolved by `anvil/engine/forward.py`: use a traded future when available
(tagged), else derive a cost-of-carry forward `F = S·e^{(r−q)T}` tagged `derived_cost_of_carry`.
Higher-order Greeks (vanna/charm/vomma) were re-derived for Black-76. Every Greek is validated by
finite-difference cross-checks, put-call parity, py_vollib agreement (when installed), and IV
round-trip.

## Consequences
- `greeks.py` signatures drop `q` and take `F` instead of spot; GEX/implied-dist/portfolio/vol were
  re-pointed accordingly.
- Forward provenance is surfaced on results (`forward_source`) and will feed the calibration ledger.
- Validate computed Greeks against a real broker chain before any production claim.
