# 0004 — Greeks via Black-76 (py_vollib + independent SciPy test oracle)

- **Date:** 2026-06-17
- **Status:** Accepted

## Context
Indian index options are priced/settled off **futures**, so Greeks must use **Black-76**, not
Black-Scholes. Kite Connect does not serve Greeks via API, so they are computed locally. This is
quant code → test-first, and validated against broker-shown values.

## Decision
- Implement the engine in `quant/black76.py` using **py_vollib's `black_76`** module, with a pure
  **NumPy/SciPy closed-form fallback** in the same module for platforms where the py_vollib wheel
  is unavailable.
- All functions take the **futures price `F`** (never spot). Inputs are raw academic units:
  `t` in years, `r` and `sigma` as decimals.
- The engine returns **raw units** (theta per year, vega per 1.00 vol, rho per 1.00). Presentation
  scaling (theta/365 per-day, vega/100 per-1%-IV) lives in `quant/greeks_service.py` and is tested
  separately, keeping the engine a clean math oracle.
- **Tests use an independent SciPy `norm` closed-form reference** — never validate py_vollib with
  py_vollib. Correctness is pinned by: known closed-form values, put-call parity
  (`C − P == e^{−rt}(F − K)`), finite-difference cross-checks of every analytic Greek, the
  Black-76 identity `rho == −t·price`, IV round-trip, and edge-case guards.
- A `broker_greeks_*.json` fixture format (per-strike tolerances) is defined now; the
  `broker_validation` test is non-gating until real broker numbers are captured, then becomes
  required.

## Why
- Black-76 is the correct model for futures-settled options; py_vollib is the spec's named library.
- An independent oracle + finite differences make the tests fail deterministically and offline when
  the math is wrong — that is the merge gate.

## Consequences
- Broker validation is pending real captured numbers (tracked in `docs/PHASE1_BACKLOG.md`).
- Unit conventions are documented and enforced by tests to avoid theta/vega scaling confusion.

## Revisit when
Real broker Greeks are captured (activate the gate) or additional Greeks (vanna/vomma/charm) are
needed for the risk book.
