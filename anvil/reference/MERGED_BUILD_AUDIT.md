# Merged Build — Brutal Audit (as actually built) & Comparison Matrices

> **Document 3.** Documents 1 (`COMPARISON_AND_MERGE.md`) and 2 (`MERGED_BLUEPRINT.md`) described
> two versions and the *plan* to merge them. This document audits the **merged version that now
> exists in code** — Phase 0 + the hardening pass + Increment 1 — and grades it **brutally against
> its own blueprint and against the two originals.** I built it, so the harshest lens applies: what
> is *actually* in the repo, verified, vs what the blueprint promised.
>
> _Author: Claude (Claude Code). Date: 2026‑06‑18. Audience: you. Tone: brutal, decision‑oriented._
>
> **Naming:** **Merged** = the current `Stock Market App - claude.ai/` repo. **OIP‑0** = that repo
> at the end of Phase 0 (the original narrow version). **Anvil** = the other version.

---

## 0. TL;DR — the honest status

- **What the merge achieved (real):** the rigorous OIP spine now carries a **broad analytics
  surface on the futures‑correct Black‑76 engine** (OI, vol/skew, GEX + zero‑gamma flip, implied
  distribution), a **multi‑index** config (7 indices), and the **calibration‑ledger substrate**
  (scoring + an append‑only reproducible store) — all **test‑first: 176 tests pass, ruff‑clean,
  demo reproducibility PASS.**
- **What it is NOT (brutal):** still **pre‑product.** The calibration ledger is an **empty vessel**
  — *nothing generates forecasts to log*, so the reliability curve (the entire moat) has **zero
  track record.** There is **no UI for the new analytics** (the static page still shows only the
  chain+Greeks), **no live data, no risk book, no regime model, no copilot, no backtesting lab.**
- **Weighted score:** **Merged ≈ 3.16** vs **Anvil 3.02** vs **OIP‑0 2.80**. The merge is the best
  of the three — but by a **modest 0.14 over Anvil**, and Anvil still beats Merged on **raw
  analytics breadth** (it has regime, higher‑order Greeks, and a beta‑weighted risk book the merge
  hasn't ported yet). The gain came on the *cheap‑to‑verify* axes (methodology, maintainability) and
  4 analytics on a correct base — **not** on the revenue‑producing axes (UX, a proven moat).
- **One‑line verdict:** *a materially better and trustworthy foundation, with the moat scaffolded
  but empty — the hard, monetizable 80% (forecasts→ledger, UI, live data, risk book) is still ahead.*

---

## 1. What the Merged version IS now (built + verified)

Every item below is in the repo and exercised by the test suite / demo (the value of this version
is that claims are demonstrable).

**Engine & correctness (from OIP‑0, unchanged, still the spine):**
- Black‑76 Greeks on the **futures price** (`quant/black76.py`, `greeks_service.py`).
- **176 tests** pass (was 147 at end of hardening; +29 in Increment 1), ruff‑clean, in Docker/3.12;
  validation = finite‑difference + put‑call parity + third‑party `vollib` agreement + reproducibility.
- Offline‑first `DataSource` protocol; deterministic/reproducible DuckDB+Parquet+SQLite storage;
  6 ADRs; CI; disclaimers everywhere.

**New in Increment 1 (the graft + the moat seed):**
- **Multi‑index** (`config.py`): lot sizes + strike steps for NIFTY, BANKNIFTY, FINNIFTY,
  MIDCPNIFTY, NIFTYNXT50, SENSEX, BANKEX.
- **`analytics/`** (computed on the future, test‑first):
  - `oi.py` — PCR (OI & volume), max pain, OI walls, buildup classification.
  - `vol.py` — ATM IV, IV smile, put/call skew, IV rank/percentile (history‑aware).
  - `gex.py` — GEX (F²‑scaled, explicit dealer sign) + zero‑gamma flip — **flagged
    `needs_nse_validation`**.
  - `implied_dist.py` — expected move (ATM‑IV + straddle) + Breeden‑Litzenberger RND — **flagged
    `needs_real_world_calibration`**.
- **`calibration/`** — `scoring.py` (Brier, log‑loss, reliability bins, coverage; known‑value
  tested) + `ledger.py` (append‑only, reproducible DuckDB forecast→outcome store, idempotent).
- **API** — `GET /analytics/{underlying}` and `GET /calibration`, disclaimer + honesty flags on
  every payload.

---

## 2. Brutal audit — blueprint claims vs merged code

The blueprint (Document 2) promised a base + grafts + a moat + delivery. Here's what is **actually
built** vs **still vapor**, in the merged repo:

| Blueprint element | Status in merged code | Brutal note |
|---|---|---|
| OIP spine (Black‑76, tests, reproducible store) | ✅ **Built & verified** | The genuine, demonstrable strength. |
| Multi‑index (7 indices) | ✅ Built (config) | But only **NIFTF has a fixture**; other indices 404 until data is added. |
| OI analytics | ✅ Built + tested | Solid. |
| Vol/skew/IV‑rank | ✅ Built + tested | IV‑rank/percentile need snapshot history that isn't being captured yet. |
| GEX + zero‑gamma flip | ⚠️ Built, **UNVALIDATED on NSE** | Conventions are US‑derived; flagged honestly. Raw GEX magnitudes are unnormalized ₹ numbers — meaningless without UI units context. |
| Implied distribution / RND | ⚠️ Built, **crude** | Sticky‑strike smile, few fixture strikes; risk‑neutral, **not** calibrated. Flagged. |
| **Calibration ledger** | 🟡 **Substrate only — EMPTY** | Data model + scoring exist and are reproducible, but **nothing logs forecasts** → 0 track record → the moat does not yet exist in usable form. |
| **Honest backtesting lab (bias‑guards as failing tests)** | ❌ **Not built** | The thing that would let any forecast be trusted. Absent. |
| **Forecast engine** (the producer of probabilities) | ❌ **Not built** | Without it the ledger has nothing to score. This is the biggest missing piece. |
| Beta‑weighted **risk book** (net Greeks, beta‑to‑NIFTY) | ❌ **Not ported** | Anvil *has* this; the merge does **not** yet. A headline pillar still missing. |
| Regime model / higher‑order Greeks (vanna/charm/vomma) | ❌ **Not ported** | Anvil has both; merge has neither yet. |
| Real UI (reliability curve + analytics dashboard) | ❌ **Not built** | Static page still shows only chain+Greeks — it doesn't even render the new analytics. |
| Live data (Upstox/Dhan/Kite/Groww) | ❌ **Not built** | Still offline fixture only. |
| Grounded copilot | ❌ **Not built** | — |
| Gated execution seam | ❌ **Not ported** | Anvil has it; merge is analysis‑only. |

**Brutal summary:** Increment 1 delivered exactly its spec (4 analytics + calibration seed on the
correct base) — and **nothing beyond it.** The merge is now a *correct, broad analytics engine with
an empty moat*. The blueprint's M2–M6 (the parts that make money) are untouched.

---

## 3. Comparison matrices

### 3.1 Capability matrix — Merged (now) vs OIP‑0 vs Anvil
| Capability | OIP‑0 | Anvil | **Merged (now)** |
|---|---|---|---|
| Greeks engine | Black‑76 (futures), tested | BSM‑on‑spot, light tests | **Black‑76 (futures), tested** ✅ |
| Test rigor | 147, multi‑strategy | ~32, light | **176, multi‑strategy** ✅ |
| OI analytics | ✗ | ✓ | ✅ |
| Vol/skew/IV‑rank | ✗ | ✓ | ✅ |
| GEX + zero‑gamma flip | ✗ | ✓ (unvalidated) | ✅ (unvalidated, flagged) |
| Implied distribution / RND | ✗ | ✓ | ✅ |
| Regime model | ✗ | ✓ | ✗ |
| Higher‑order Greeks | ✗ | ✓ | ✗ |
| Beta‑weighted risk book | ✗ | ✓ | ✗ |
| Multi‑index | seeded (2) | ✓ (7) | ✅ (7 config; 1 fixture) |
| Calibration ledger | ✗ | claimed, ✗ | 🟡 substrate, **empty** |
| Backtesting lab | ✗ | ✗ | ✗ |
| Reproducible data store | ✓ | partial | ✅ |
| Live data | ✗ | stubs | ✗ |
| Execution seam | ✗ | ✓ (gated) | ✗ |
| UI | static page | CLI | static page (not updated) |
| Disclaimers / honesty flags | ✓ | ✓ | ✅ (+ per‑analytic flags) |

**Reading:** the merge **closed OIP‑0's biggest gap** (analytics breadth) on a correct engine — but
**has not yet absorbed all of Anvil's breadth** (regime, higher‑order, risk book), and **neither the
merge nor Anvil has a working moat.**

### 3.2 Plan vs built — blueprint roadmap completion
| Phase | Scope | Built? |
|---|---|---|
| Phase 0 + hardening | Engine + storage + API + tests | ✅ 100% |
| **M1** — breadth on correct base | OI, vol, **GEX**, implied‑dist, multi‑index | ✅ ~70% (missing regime, higher‑order, **risk book**) |
| **M2** — calibration ledger + backtest lab | ledger substrate + scoring | 🟡 ~40% (substrate only; **no forecast producer, no backtest lab**) |
| **M3** — real UI | reliability curve + dashboard | ❌ 0% |
| **M4** — live data | brokers + NSE | ❌ 0% |
| **M5** — grounded copilot | Claude tool‑use | ❌ 0% |
| **M6** — monetization activation | education → retail → data/API | ❌ 0% |

### 3.3 Weighted scorecard (three‑way)
Same weights and 1–5 scale as Document 2.

| Dimension | Weight | OIP‑0 | Anvil | **Merged** | Why Merged scores thus |
|---|---|---|---|---|---|
| Defensible moat (data/ledger/network) | 20% | 3 | 3 | **3** | Substrate built + reproducible, but **track record = 0**. No real gain in the *asset*, only the scaffold. |
| Honest, validated methodology | 15% | 4 | 2 | **4** | 176 tests; analytics deterministically tested (GEX sign, RND normalization, known‑value Brier). |
| Analytics depth | 12% | 1 | 4 | **3** | 4 analytics on a correct engine — but **still below Anvil**: no regime, higher‑order, or risk book. |
| Build maturity / time‑to‑market | 12% | 2 | 3 | **3** | Broad + tested + calibration substrate; still no UI/live/forecasts. |
| Compliance / SEBI safety | 10% | 4 | 4 | **4** | Disclaimers + per‑analytic honesty flags + analysis‑only. |
| Monetization clarity & WTP | 10% | 3 | 4 | **3** | Strategy is documented, but **nothing new is monetizable yet**; Anvil's unit‑economics framing still sharper. |
| AI/agent quality & grounding | 8% | 2 | 2 | **2** | Not built. |
| UX / delivery readiness | 7% | 2 | 2 | **2** | Static page doesn't even show the new analytics. |
| Tech maintainability & scalability | 6% | 4 | 3 | **4** | ADRs, CI, reproducibility, clean module boundaries. |
| **Weighted total** | 100% | **2.80** | **3.02** | **3.16** | Best of three — but modestly. |

**Brutal read of the score:** the +0.36 over OIP‑0 is almost entirely "analytics depth 1→3" +
"maturity 2→3" — real, but the *cheap‑to‑build* axis. The +0.14 over Anvil is "methodology" and
"maintainability" — i.e., the merge bought **correctness and trustworthiness**, not **revenue
surface**. The four dimensions that actually print money (moat realized, monetization, UX, and a
forecast/AI layer) **did not move** — they're still 2–3.

---

## 4. What moved the needle — and what conspicuously didn't

**Genuinely improved (verified):**
- Analytics breadth on a **futures‑correct, tested** engine (vs OIP‑0's nothing, and vs Anvil's
  spot‑approximated, lightly‑tested versions).
- The calibration **substrate** now exists in a reproducible store with known‑value‑tested scoring.
- Multi‑index plumbing.

**Did NOT improve (brutal):**
- **The moat itself.** Zero forecasts logged ⇒ zero reliability track record. The headline asset is
  still hypothetical.
- **Anything a user sees.** No UI for the new analytics; the static page is unchanged.
- **Breadth vs Anvil.** Anvil still has regime + higher‑order + a beta‑weighted risk book that the
  merge lacks. On raw feature count, **Anvil is still ahead.**
- **Live‑ness.** Still offline fixture; the data flywheel hasn't started turning.

---

## 5. Brutal weaknesses of the merged version (today)

1. **An empty moat is not a moat.** The calibration ledger's value is entirely in its track record,
   which is zero and stays zero until a forecast engine + a daily logging job exist. Right now it's
   impressive plumbing attached to nothing.
2. **GEX is shippable‑looking but unvalidated.** US sign/level conventions; raw ₹ magnitudes;
   flagged but not yet proven on NSE. Showing it as a signal today would violate the trust thesis.
3. **The risk book — a headline pillar — is missing.** Both Anvil and the blueprint have it; the
   merge doesn't. A "unified cross‑broker risk view" is a core selling point and it's absent.
4. **No delivery surface.** API‑only; nobody can *use* the analytics without building a client.
5. **Single‑fixture, single‑expiry.** Multi‑index is config‑only; only NIFTY has data; everything
   runs off one committed snapshot. None of it is live.
6. **It is still a foundation, dressed up by good docs.** The strategy documents are strong; the
   product is not yet there. Don't confuse the two.

---

## 6. Risks if you stopped here
- **You have a beautiful engine and no business.** Every revenue path needs the pieces that don't
  exist (proven ledger, UI, live data).
- **The moat clock hasn't started.** Calibration credibility takes months of logged forecasts; not
  starting that loop is the single most expensive delay.
- **Feature parity illusion.** It's tempting to call the merge "done" because it's broad and tested;
  on the axes that matter for money it trails its own plan badly (M2–M6 at ~0–40%).

---

## 7. Highest‑leverage next increments (to turn foundation → product)
In strict priority order (each makes the next worth more):
1. **Forecast producer + start logging to the ledger** — even a simple, honest model (e.g.,
   expected‑move band probabilities from the implied distribution) logged daily. *This starts the
   moat clock and is the single highest‑leverage thing left.*
2. **Honest backtesting lab** (bias‑guards as failing tests) — so any forecast is validated before
   it's trusted/shown.
3. **Beta‑weighted risk book** — port it onto Black‑76 (close the missing pillar; high user value).
4. **Real UI** — render the analytics **and the reliability curve** (the curve is the whole pitch).
5. **Live data** (Upstox/Dhan + Kite/Groww positions) — start the real data flywheel.
6. Regime + higher‑order Greeks; then copilot; then monetization activation.

---

## 8. Decision / next step
- **Honest position:** the merged version is the **best of the three and the right base**, but it is
  **~1/5 of the way to a monetizable product** (Phase 0 + part of M1/M2 of a 6‑phase plan).
- **Recommended next:** build increment 2 = **forecast producer → ledger logging + the backtest
  lab** (start the moat clock), then the **risk book** and a **UI that shows the reliability curve**.
- Say the word and I'll take increment 2.

_End of Document 3._
