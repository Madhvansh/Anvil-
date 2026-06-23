# Anvil (Merged) — Brutal Self-Audit & Three-Way Comparison

> **What this is.** A deliberately harsh, evidence-based audit of the **merged version** I built
> (Anvil base + OIP correctness spine), plus side-by-side matrices vs **Version A (original Anvil)**
> and **Version B (OIP)**. Written to be compared against the two earlier dossiers
> (`Anvil-vs-VersionB-Comparison.md`, `COMPARISON_AND_MERGE.md`). I am turning the same brutal lens
> I used on A and B onto my own work — no marketing.
>
> _Author: Claude (Claude Code). Date: 2026-06-18. Disclaimer: analytics/education, not advice._

---

## 0. TL;DR (the honest version)

The merge did exactly what it set out to do **on paper**: it fixed Anvil's real correctness bug
(now Black-76 on the futures price), raised the test bar (25 → **96 tests**, with finite-difference
/ parity / py_vollib / IV-round-trip), and added the four things *neither* original had — a
calibration ledger, live-broker auth + a gated order gateway, a grounded agent, and a web UI.

**But be clear about what that is and isn't.** Everything is verified **offline, on synthetic
data**. **Nothing has touched a live broker API. The reliability curve is seeded with synthetic
forecasts — there is zero real track record. There is no backtester, so there is no validated
edge.** This is a *correct, rigorous, feature-complete foundation* — not a production-live system
and not a proven money-maker. The gap between "the code runs" and "this makes money in the market"
is still almost entirely unclosed.

---

## 1. What the merged version actually is

- **Base:** Version A (Anvil) — kept its analytics (GEX/flip, Breeden-Litzenberger, beta-weighted
  Greeks, regime, OI, vol), connectors, FastAPI, CLI.
- **Grafted from B:** the **Black-76-on-futures** engine, the finite-diff/parity/py_vollib/IV
  validation bar, Docker (Python 3.12), CI, ADRs.
- **Net-new (in neither original):** `anvil/ledger/` (calibration), `anvil/auth/` (Upstox OAuth,
  Kite login, token store), `anvil/ingest/groww.py` + `anvil/execution/groww_gateway.py` (gated),
  `anvil/agent/` (narrator + guardrail), `anvil/api/static/index.html` (web UI), and a hardened
  `anvil/store/timeseries.py` (idempotent snapshots + chain time-series + audit + Parquet).

---

## 2. Brutal audit — REAL vs THEATER

| Component | Status | The brutal truth |
|---|---|---|
| **Black-76 engine** | ✅ Real, math-validated | Correct model, checked vs finite differences + py_vollib + parity. **But "validated" = vs math, NOT vs a real broker's shown Greeks.** Until reconciled against a live NSE chain, it's correct-in-theory. |
| **Analytics (GEX/flip, RND, β-Greeks, regime, OI, vol)** | ✅ Real, tested on synthetic | All compute and are unit-tested — **on the demo chain only.** The GEX dealer-sign convention and the zero-gamma flip are *assumptions* unproven on real NSE positioning. The regime read is a transparent rules engine, not a validated predictor. |
| **Connectors (Upstox/Dhan/Kite/Groww/NSE)** | ⚠️ Coded, **never run live** | Zero live calls. **Groww's chain parsing uses field names *inferred from research docs*, not verified against a real payload — it will very likely need fixes on first real call.** The NSE EOD scraper is best-effort and brittle by nature. |
| **Auth (Upstox OAuth, Kite login, token store)** | ⚠️ Partly tested | Token store + Kite checksum + dialog-URL builder are unit-tested. **The actual OAuth dance, loopback capture, and token exchange have never executed** (no credentials). |
| **Calibration ledger** | ⚠️ Mechanics real, data synthetic | Record/resolve/scoring (Brier/log-loss/ECE/reliability/coverage) are tested and correct. **The reliability curve shown in demos is from `ledger seed` — synthetic, well-calibrated-by-construction data. Real resolved forecasts: zero.** The moat is *plumbed*, not *accrued*. |
| **Order gateway (Groww, gated)** | ⚠️ Logic real, never placed an order | Dry-run / `--live` / confirm gating is tested with a fake SDK. **No real order has ever been sent; the Groww param/constant mapping is unverified against the live SDK.** |
| **Grounded agent** | ⚠️ Narrator real, LLM path untested | The deterministic narrator + the compliance guardrail are tested. **The Claude Q&A path has never run (no API key).** The guardrail is **regex heuristics — evadable, and NOT a substitute for legal/compliance review.** |
| **Web UI** | ⚠️ Renders, untested as UX | Serves HTTP 200 and renders the payload. No real frontend framework, no auth, no multi-user, no responsive/QA testing, no real-time. |
| **Infra (Docker/CI/ADRs/git)** | ⚠️ Defined, not exercised here | The Dockerfile and CI workflow are written but **were not built/run in this environment.** The git repo is **initialized and staged but not committed**, and the M3–M5/M2 modules are currently **untracked**. |
| **Tests (96)** | ✅ Real, but shallow-by-design | All **offline/synthetic unit tests**. No live integration, no property-based, no load/perf, no end-to-end against real APIs. Breadth of units, not depth of integration. |
| **Backtesting lab** | ❌ Not built | Therefore **no validated trading edge of any kind.** |

---

## 3. Overclaim check (the lens, on myself)

- *"Futures-correct Greeks"* — true mathematically; **unproven against the market.**
- *"Calibration ledger working"* — mechanically yes; **the track record is synthetic.**
- *"Live data / broker auth"* — code exists; **nothing has authenticated or fetched a live quote.**
- *"96 tests passing"* — true and meaningful for the math, but it is **not** evidence the product
  works end-to-end, makes money, or survives a real API.
- *"Gated execution"* — true; but "we built the safety gate" is not "we safely traded."
- **Architecture caveat:** the merge kept Anvil's flatter layout as the base and grafted B's
  *engine + practices* — it did **not** adopt B's cleaner domain/data/quant/storage layering. We got
  B's correctness and discipline, not its architectural separation.

---

## 4. Three-way comparison matrices

### 4.1 Product & strategy
| Dimension | A — Anvil (orig) | B — OIP | **Merged** | Verdict |
|---|---|---|---|---|
| Core identity | Position-aware regime analyst | Calibration-first analyst | **Both, unified** | Merge keeps the sharper wedge |
| Prediction stance | Calibrated (but wrong engine) | Calibrated (correct engine) | **Calibrated + correct + ledgered** | Merge resolves it |
| Differentiation / moat | Analytics breadth | Correctness + rigor | **Breadth + correctness + ledger plumbing** | Stronger, still unproven |
| Compliance posture | Disclaimers, gated | Probabilistic, analysis-only | **Disclaimers + guardrail + gated** | Best of the three; heuristic only |
| Honest track record | none | none | **none (synthetic seed)** | Unchanged — the real gap |

### 4.2 Technical & data
| Dimension | A | B | **Merged** | Verdict |
|---|---|---|---|---|
| Greeks engine | BSM on **spot** (wrong) | **Black-76 futures** (correct) | **Black-76 futures** | Bug fixed |
| Validation bar | 25 tests, no finite-diff | 51 tests, finite-diff/vollib | **96 tests, finite-diff/vollib/parity/IV** | Highest |
| Analytics depth | GEX/RND/β-Greeks/regime/OI/vol | none built | **all of A's, on the correct engine** | Merge wins decisively |
| Connectors | Upstox/Dhan/Kite (stubs) + demo | fixture + NSE-capture | **+ Groww + auth + token store** | More, still un-live |
| Storage | single DuckDB table | Parquet+SQLite, idempotent | **DuckDB idempotent + chain time-series + audit + Parquet export** | Rigorous |
| Architecture | flat | clean layered | **flat (A's) + B's practices** | Compromise, not ideal |
| Infra | none | Docker/CI/ADRs | **Docker/CI/ADRs (defined, unrun)** | Adopted |

### 4.3 AI, execution, delivery, money
| Dimension | A | B | **Merged** | Verdict |
|---|---|---|---|---|
| AI / agent | none | specified only | **narrator + guardrail (LLM path untested)** | Real but partial |
| Calibration ledger | none | designed | **built + tested (synthetic data)** | Plumbed |
| Execution | gated skeleton | analysis-only | **gated Groww gateway, dry-run default** | Safest; never fired |
| Delivery / UX | CLI + API | static page | **CLI + API + web cockpit** | Best; basic |
| Monetization model | tiers + rev-share | 4 layers | **same thesis, now with the ledger to enable it** | Unchanged thesis, unproven |

---

## 5. Weighted scoring (1–5 × weight)

| Dimension | Weight | A | B | **Merged** |
|---|---|---|---|---|
| Defensible moat (data/ledger/network) | 20% | 2 | 2 | **3** |
| Honest, validated prediction methodology | 15% | 2 | 3 | **3** |
| Analytics depth | 12% | 4 | 1 | **5** |
| Build maturity / time-to-market | 12% | 3 | 3 | **4** |
| Compliance / SEBI safety | 10% | 3 | 4 | **4** |
| Monetization clarity & WTP | 10% | 3 | 3 | **3** |
| AI / agent quality & grounding | 8% | 1 | 1 | **3** |
| UX / delivery readiness | 7% | 2 | 2 | **3** |
| Tech maintainability & scalability | 6% | 3 | 4 | **4** |
| **Weighted total / 5** | 100% | **2.54** | **2.49** | **3.52** |

**Read this honestly:** the merge is a clear win over either original (**3.52** vs 2.54 / 2.49) —
but **3.52/5 is a "strong foundation," not "ready."** The score is dragged down exactly where it
should be: validated methodology, a real (non-synthetic) moat, and live-readiness. The two lowest
real-world scores — **validated trading edge ≈ 1/5** and **live/production readiness ≈ 2/5** — are
not in the rubric above and are the true blockers.

---

## 6. What the merge resolved — and what it did NOT

**Resolved:** the wrong pricing model; the weak test bar; the missing calibration plumbing; the
missing auth/execution scaffolding; the absent agent and UI; loose storage. One correct,
disciplined, version-controlled codebase.

**Did NOT resolve (still wide open):**
1. **No live validation** — not one real broker call; Groww parsing likely broken until tested.
2. **No real track record** — the ledger is empty of genuine resolved forecasts.
3. **No backtester** — zero evidence of edge; the regime read is unvalidated.
4. **No legal/compliance review** — the guardrail is regex, not a lawyer.
5. **Architecture compromise** — kept the flatter base.
6. **Infra unrun** — Docker/CI defined but never executed here; repo uncommitted.

---

## 7. Risks (brutal)

- **First live integration will break things** (especially Groww's inferred schema and the NSE
  scraper). Confidence from green offline tests is partly false comfort.
- **The synthetic reliability curve could be mistaken for a real one** in a demo — that would be
  exactly the dishonest "accuracy" claim the whole design exists to avoid. Label it relentlessly.
- **Heuristic guardrail evasion** — an LLM can phrase advice the regex misses. Don't ship the LLM
  Q&A to users without a stricter, reviewed guard + counsel.
- **Single-developer, single-session provenance** — no second pair of eyes on the quant beyond the
  automated checks; finite-diff guards the formulas, not the modeling choices (dealer-sign,
  smile smoothing, forward derivation).

---

## 8. Honest verdict

The merged version is **the best of the three by a clear margin and the right base to continue on** —
correct, tested, feature-complete, compliant-by-design. It is **not** yet a product that makes
money or can go live. To change that, in priority order: **(1) reconcile Greeks against a real
Upstox chain; (2) run the connectors live and fix what breaks; (3) start accruing a *real*
calibration track record; (4) build the backtesting lab to test for any edge; (5) get SEBI counsel
before any accuracy marketing or auto-execution.** Until (1)–(4) are done, the honest label is:
*"a rigorous, futures-correct analytics foundation with the trust/monetization machinery plumbed but
unproven."*
