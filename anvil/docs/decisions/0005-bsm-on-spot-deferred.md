# ADR 0005 — BSM-on-spot for single-stock options: deferred (not built, not needed yet)

**Date:** 2026-06-23 · **Status:** Deferred (recorded to close the 0004→0006 numbering gap)

## Context
ADR [0002](0002-greeks-black76-on-futures.md) replaced Anvil's original spot-BSM engine with
**Black-76 on the forward** for Indian *index* options (NIFTY/BANKNIFTY/…), which are European and
settled off the futures. A separate question was left open by the wave plans (`revamp/W3.md` §M2):
*single-stock* equity options in India are **physically settled** and quoted against spot, so a
faithful pricer for them would be Black-Scholes-Merton on **spot** (with a discrete-dividend / borrow
adjustment), not Black-76 on a future. Because ADR [0004](0004-calibration-first-compliance.md) and
ADR [0006](0006-personal-mode-hard-wall.md) make parts of the surface *actionable and sized*, the
documentation must be honest about exactly which pricing models are in use — and must not imply a
spot-BSM capability that does not exist.

This ADR records the deliberate decision **not** to build it now, and the trigger that would reopen it.

## Decision
**Do not build BSM-on-spot.** It is unnecessary at the current product scope:
- **Index options** price via **Black-76 on the forward** `F` (`engine/greeks.py`, resolved by
  `engine/forward.py` — traded future when available, else a tagged cost-of-carry forward). The
  `greeks.py` docstring is explicit: *"never Black-Scholes on spot."* There is **no** spot-BSM path
  anywhere in the engine.
- **Single-stock tips** are **directional cash positions, not option structures.** The cross-sectional
  equities engine (`factors/equities.py`, `tips/equities.py`) projects each long/short into a single
  **linear `EQ` leg** (`instrument_type="EQ"`), because single-stock option chains are thin/illiquid;
  the edge is directional, resolved against the cash close. No single-stock option is priced, sized, or
  traded — so no single-stock option pricer (BSM-on-spot or otherwise) is required.

Therefore the doc set states "Black-76 on futures" for index options and makes **no** claim of
single-stock-option pricing. The honesty-lint test (`tests/test_docs_honesty.py`) enforces that no doc
asserts a positive spot-BSM capability (only the negation "never BSM on spot" is permitted).

## Consequences
- No pricing ambiguity: every Greek in the live engine is Black-76 on the forward; nothing prices on
  spot. This ADR makes the absence of spot-BSM an explicit, recorded decision rather than a silent gap.
- The ADR numbering is contiguous again (0001–0006); the live `docs/decisions/` tree no longer skips
  0005. (Note: a *different* `0005` in the stale `reference/docs/decisions/` tree is unrelated history.)

## When to revisit
Promote this from a deferral to a real decision (and build the spot-BSM pricer + its validation battery,
mirroring ADR 0002's finite-difference / parity / IV round-trip bar) **iff** a future wave actually
trades single-stock physically-settled **option structures** (e.g. stock spreads, synthetics, or
covered/secured single-stock premium selling). Until single-stock options are priced or traded, this
stays Deferred.
