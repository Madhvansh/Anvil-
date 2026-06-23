# Options Intelligence Platform — Build Dossier & Merge Framework

> **What this document is.** You built **two versions of the same idea** (an India
> options‑intelligence product) and want to compare them and merge the best of both into one. This
> file is **Document 1**: a complete, standalone dossier of **this** version — the *Options
> Intelligence Platform* (the codebase in `Stock Market App - claude.ai/`). It covers my thought
> process, what actually exists today, my honest read of the idea, the innovations, how it makes
> money, and the hard questions — plus a comparison framework with only this version filled in, so
> the later merge stays symmetric.
>
> **It is deliberately self‑contained.** It does not reference, borrow from, or pre‑judge your other
> version. The actual side‑by‑side comparison, weighted score, and merge blueprint come in
> **Document 2** (`MERGED_BLUEPRINT.md`), written after I read the other version's dossier on its
> own terms.
>
> _Author: Claude (Claude Code). Date: 2026‑06‑17. Audience: you (a candid, decision‑oriented
> internal doc, not a pitch)._
>
> **Disclaimer baked into the product:** everything here describes *computed analytics and
> probabilistic context*, never investment advice, and never a claim of "high accuracy."

---

## 0. TL;DR (one screen)

- **The product.** A calibrated options‑intelligence platform for Indian markets (NSE/BSE). It does
  not sell predictions; it sells **probabilities with a live, auditable track record of how well
  those probabilities are calibrated.** The headline a tipster cannot copy: *"We don't promise
  accuracy. Here's our reliability curve."*
- **The wedge.** Trust, earned through transparency, in a market saturated with "90% accuracy"
  tipsters. Calibration + probabilistic framing + disclaimers is simultaneously the honest thing,
  the thing that protects users, and the single strongest differentiator.
- **What exists today.** A **Phase‑0 vertical slice**, built test‑first and verified end‑to‑end:
  ingest an option chain → compute **Black‑76 Greeks on the futures price** → store → query →
  display, all runnable offline with **zero credentials**. **147 automated tests pass**; the quant
  core is validated by independent math (finite differences, put‑call parity), a third‑party
  library cross‑check, and a reproducibility self‑check. Hardened by an adversarial multi‑agent
  review (11 fixes applied).
- **What's not built yet.** The forecast/calibration engine, the cross‑broker risk book, live
  broker connectivity, the AI copilot, the backtesting lab, and any real UI beyond a static page.
  This is a **rigorous foundation**, not a finished product.
- **The asset that makes money.** **Deep analysis across *all* the liquid Indian indices**
  (NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTY NEXT 50, SENSEX, BANKEX), plus the proprietary,
  ever‑growing calibration dataset that proves the analysis is honest. Every monetization path
  (subscription, data/API licensing, personal/prop edge, education/community) is downstream of that
  one asset.

---

## 1. My perception of the idea (the honest thesis)

The seductive version of this idea — *"connect my broker, read the option chain, and predict the
market accurately"* — is half right and half trap. My honest read:

- **Point prediction of index direction is not honestly sellable.** On liquid Indian indices,
  out‑of‑sample directional calls cluster near coin‑flip after costs. Anyone advertising 80–90%
  "accuracy" is almost always fooling themselves with look‑ahead bias, overfitting, or
  survivorship — and in India, selling that as a recommendation is also **SEBI Research‑Analyst
  liability.** A product built on a fake hit‑rate has a half‑life measured in months.
- **But several things genuinely *are* forecastable to useful precision:** expected‑move ranges,
  volatility regimes, relative value, event‑vol behaviour (IV crush around budgets/RBI/earnings/
  expiry), and the *probability* of touching or closing within a band. The model's job is to widen
  uncertainty honestly where the signal is weak, not to fake confidence.
- **So the real, defensible position is "calibrated, not accurate."** Every output is a
  probability or a distribution, and every probability ships with a **live calibration score**
  (Brier score, reliability diagram, band‑coverage) computed on *realized* outcomes. That reframes
  the entire category: instead of competing on a louder accuracy claim, you compete on being the
  only one willing to *show your reliability curve*.
- **The moat is trust + data, not features.** Any single analytic (Greeks, OI, a vol surface) is
  copyable in a quarter. What compounds and cannot be back‑filled is a **multi‑year public
  calibration ledger** ("when we say 70%, it happens about 70% of the time") and the **cleaned,
  proprietary time‑series** of chains/Greeks/vol‑surfaces it's computed from.

**Identity in one line:** *the options‑intelligence platform that proves calibration instead of
claiming accuracy — and gives a trader a unified, broker‑agnostic risk view that no broker‑locked
tool does.*

---

## 2. My thought process — the decisions that define this version

Every decision below is recorded as a dated Architecture Decision Record in
`docs/decisions/` so future work inherits the *why*, not just the *what*.

| Decision | What I chose | Why |
|---|---|---|
| **Prediction framing** | Calibrated **probabilities / distributions**, with calibration shown alongside every forecast | Honest, SEBI‑defensible, and a stronger wedge than any accuracy claim. No "high accuracy"/guaranteed‑return language anywhere in code, copy, or UI. |
| **Greeks model** | **Black‑76 on the futures price** (not Black‑Scholes on spot) | Indian index options are priced/settled off futures; Black‑76 is the correct model. The engine takes the futures price `F` as a first‑class input. |
| **Greeks provenance** | Computed **locally**, validated against broker‑shown values | Broker APIs don't reliably serve Greeks; owning the math is both correct and the start of a data moat. |
| **Correctness discipline** | **Test‑first** for all quant; the test suite is the merge gate | Correctness is *earned, not asserted*. A wrong Greek fails the build, not a code review. |
| **Backtester integrity** | Look‑ahead & survivorship guards as **failing tests** (planned) | A backtester that can be "tuned until it looks good" is worse than none. Bias guards must break the build, not warn. |
| **Data strategy** | **Offline‑first** behind a `DataSource` protocol; real brokers plug in later | The whole thing runs with zero credentials, deterministically, today — and live Kite/Groww/NSE become drop‑in implementations of the same interface. |
| **Storage** | **DuckDB + Parquet** (analytics) + **SQLite** (metadata) now; Postgres/Timescale + Redis deferred | Start hoarding clean data from day one with zero infra; add the heavy stack only when ingest volume and live caching justify it. |
| **Runtime** | **Docker, pinned Python 3.12** | The host runs bleeding‑edge Python 3.14 where several quant wheels lag; a pinned container makes every run reproducible regardless of host. |
| **Scope of v1** | **Analysis only** — no live order placement | Ship trust and insight first; execution carries regulatory and safety weight that should come after the analytical core is proven. |
| **Disclaimers** | A **product feature**, present on every computed surface | Probabilistic‑not‑advice framing protects users and reinforces the brand. |

---

## 3. What already EXISTS (built and verified)

This is the part I want to be precise about, because the value of this version is that its claims
are **demonstrable**, not aspirational. Everything below is committed to git (two commits:
the Phase‑0 foundation, then a hardening pass) and verified inside the Python‑3.12 container.

### 3.1 The thin vertical slice (end‑to‑end)
`ingest a chain → compute Black‑76 Greeks → store → query → display`, runnable offline with no
credentials via `docker compose`.

- **Quant core — `backend/src/oip/quant/black76.py`** — `price / delta / gamma / vega / theta /
  rho / implied_vol / all_greeks`, all on the **futures price `F`**. The engine returns *raw*
  academic units; presentation scaling (theta per day, vega per 1% IV, rho per 1% rate) lives in
  `greeks_service.py`, keeping the engine a clean math oracle. Pricing/IV use the `vollib` Black‑76
  implementation with a self‑contained SciPy closed‑form fallback; the analytic Greeks are computed
  in closed form.
- **Data layer — `backend/src/oip/data/`** — a `DataSource` protocol with a default
  `FixtureDataSource` (replays a committed, NSE‑shaped option‑chain fixture) and a capture‑only
  `NsePublicDataSource`. `normalize.py` converts raw chains into a typed model, converts IV % →
  decimal, and handles the spot‑vs‑future gap by **tagging** the futures price source
  (`nse_futures` if recorded, else a derived cost‑of‑carry forward) so a Greek is never silently
  computed off the wrong underlying.
- **Storage — `backend/src/oip/storage/`** — DuckDB over partitioned **Parquet** for chain
  snapshots and computed Greeks, plus **SQLite** for operational metadata (a snapshot registry and
  an ingest‑run audit). Snapshot IDs are deterministic, so re‑ingesting the same data is idempotent
  and reproducible.
- **Pipeline + API — `backend/src/oip/pipeline/`, `…/api/`** — an ingest pipeline and a FastAPI
  service: `GET /health`, `GET /chain`, `GET /chain/{snapshot_id}`, `GET /greeks`, plus a static
  page that renders the chain + Greeks with a **persistent, non‑dismissible disclaimer** and a
  "Black‑76 (futures‑settled)" label. Every response carries a `disclaimer` field.
- **Proof script — `backend/scripts/demo_phase0.py`** — runs the whole pipe and then **asserts the
  re‑read Greeks equal the freshly computed ones** (a reproducibility self‑check) before exiting 0.

### 3.2 The evidence (why I trust it)
- **147 automated tests pass**, ruff‑clean, in the pinned 3.12 container. The quant core is pinned
  by *four independent* strategies, not one:
  1. **Known closed‑form values** recomputed from the Black‑76 formula via an independent SciPy
     reference (never validate the engine with itself).
  2. **Put‑call parity** `C − P == e^{−rt}(F − K)` across a strike/tenor/vol grid.
  3. **Finite‑difference cross‑checks** of *every* analytic Greek against numerical derivatives of
     the price — the real "are the Greeks actually right" guard.
  4. **Third‑party agreement** with the `vollib` Black‑76 implementation, plus an **IV round‑trip**
     and explicit **edge‑case guards** (raises, not NaNs, on bad inputs).
- **Reproducibility:** storage round‑trips Greeks bit‑for‑bit; the demo's self‑check enforces it.
- **Hardened:** after the build, I ran an **adversarial multi‑agent review** (independent reviewer
  lenses → a skeptic that tries to refute each finding). It surfaced 18 candidates; **11 were
  confirmed real and fixed** (defensive IV parsing, never‑fabricate a real‑future tag, symbol
  canonicalization, multi‑expiry join correctness, JSON‑safe storage reads, connection lifecycle +
  SQLite WAL, risk‑free‑rate validation, full‑disclaimer banner, …), each with a regression test;
  7 were correctly dismissed as non‑bugs. Test count went 133 → **147** as a result.
- **Decisions are documented:** six ADRs in `docs/decisions/` and a tracked deferral log in
  `docs/PHASE1_BACKLOG.md`.
- **CI exists:** `.github/workflows/ci.yml` builds the 3.12 image, lints, runs the unit+validation
  gate, and runs the demo as an offline smoke test; live‑NSE and broker‑validation jobs are
  non‑gating.

### 3.3 What is explicitly NOT built yet
Stated plainly so the comparison is fair (see §9 for the full list): the forecast + calibration
engine, the calibration dashboard, the cross‑broker risk book, live broker auth, the analyst
copilot, the backtesting lab, the behavioral journal, and any UI beyond the static page. **Phase 0
is a foundation.** Its job was to make the *hard, correctness‑critical core* trustworthy first.

---

## 4. Architecture — current and target

**Current (Phase 0):**
```
Static page (FastAPI-served)
        │  REST
FastAPI  ──  /health /chain /greeks
        │
Pipeline (ingest)  ──  DataSource protocol (FixtureDataSource | NsePublicDataSource)
        │
Black-76 Greeks engine (futures price)  +  greeks_service (presentation units)
        │
Storage:  DuckDB + Parquet (snapshots, greeks)  +  SQLite (registry, audit)
```

**Target (the 7 pillars in `NORTH_STAR.md` / `PROJECT_SPEC.md`):**
1. **Calibrated forecast engine** — an ensemble (implied + statistical/GARCH + ML) emitting
   probability bands, probability‑of‑touch, directional odds, and expected‑move cones — each with a
   **live calibration surface** (Brier, reliability diagram, coverage). *This is the heart.*
2. **Cross‑broker unified risk book** — net Greeks + **beta‑weighted‑to‑NIFTY** exposure across
   brokers; scenario grid (spot × IV) and **Monte‑Carlo P&L** with tail risk.
3. **Event & regime intelligence** — event‑aware (budget/RBI/earnings/expiry/F&O ban),
   regime‑conditional forecasts, explicit **IV‑crush warnings**.
4. **Flow & positioning intelligence** — participant‑wise OI (FII/DII/Pro/Client) decoded into
   plain‑language narratives; an unusual‑options‑activity scanner.
5. **Analyst copilot** — natural‑language interrogation of the live book + chain + models, grounded
   strictly in engine outputs (no freeform price calls).
6. **Honest backtesting lab** — walk‑forward, out‑of‑sample, cost/slippage‑aware, with bias guards
   as failing tests.
7. **Behavioral trade journal** — surfaces the user's own decision leaks over time.

The architecture is intentionally **layered and service‑oriented** so each pillar can be built and
reasoned about in isolation, and so the offline `DataSource` seam swaps to live brokers without
touching anything downstream.

---

## 5. Innovations — what's novel / defensible here

1. **Calibration as a first‑class product surface, not a footnote.** Most tools show a number; this
   one shows the number *and its track record of being right*. Building the scoring loop
   (forecast → realized outcome → Brier/reliability) into the data model from the start is the
   defensible, compounding asset.
2. **Futures‑correct Greeks, validated against reality.** Using Black‑76 on the futures price (not
   Black‑Scholes on spot) and validating against broker‑shown values is a correctness stance most
   retail tools get subtly wrong. The futures‑price *source* is tagged and auditable.
3. **Bias‑guards‑as‑failing‑tests backtester.** Encoding look‑ahead and survivorship checks as
   tests that *break the build* is how the backtester stays honest under the pressure to make
   results look good. (Designed; to be built in the lab pillar.)
4. **Offline‑first, reproducible quant.** The whole pipe runs deterministically with zero
   credentials, and stored results re‑read bit‑for‑bit. That makes the system testable, auditable,
   and demoable — and is the substrate for a trustworthy calibration ledger.
5. **Disclaimers and probabilistic framing as a trust spine, not legal cover.** The honesty is the
   marketing. It's the one thing a "90% accuracy" competitor structurally cannot copy without
   failing their own claim.

---

## 6. Deep multi‑index analysis as the core asset

Your framing is right: the product's real asset isn't any single screen — it's **deep, calibrated
analysis across every liquid Indian index**, and the proprietary dataset that accumulates from
doing it every day. Monetization decisions flow *from* that asset.

**Indices in scope** (NSE + BSE): **NIFTY 50, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTY NEXT 50,
SENSEX, BANKEX** — each with its own lot size, strike spacing, expiry rhythm, and liquidity
profile. The architecture already treats the underlying as a parameter (Phase 0 seeds NIFTY and
BANKNIFTY; adding an index is configuration, not a rewrite).

**What "deep analysis" means, per index:**
- Full **Black‑76 Greeks** surface (δ/γ/θ/ν/ρ) on the futures price, per strike and expiry.
- **Expected‑move cones** and **probability‑of‑touch / close‑within‑band** from the implied vol
  surface and term structure.
- **IV regime** (calm / trending / stressed / event) and **IV‑rank/percentile** context.
- **OI & positioning** (PCR, max pain, OI walls, buildup classification) and, later,
  participant‑wise OI narratives.
- **Event overlays** (budget / RBI / earnings / expiry / F&O‑ban), with IV‑crush warnings.
- **Cross‑index relative value** — e.g., where NIFTY vs BANKNIFTY vol or skew is rich/cheap.

**Why breadth is the moat, not a feature:** doing this for *one* index is a screen anyone can clone;
doing it **consistently across all of them, every day, and storing the cleaned result** builds two
things competitors can't back‑fill — (a) a **cross‑index calibration record** that proves the
analysis is honest, and (b) a **proprietary historical OI/Greeks/vol‑surface dataset**. Those two
assets are what the money is actually sold against.

---

## 7. How it makes money (monetization)

The product can be monetized four ways. They are not mutually exclusive; they're **layers on the
same asset** (deep multi‑index analysis + the calibration dataset). I'll give the candid version,
including the India‑specific constraints, and a suggested sequence.

### 7.1 The four paths

**A) Retail subscription SaaS (largest TAM, most competition).**
Active F&O retail/prosumers in India already pay for analytics tools. The pull here is the one thing
they can't get elsewhere: **calibrated probabilities with a public reliability curve**, plus a
unified cross‑broker risk view.
- *Sketch tiers:* **Free** (chain, OI, PCR, max‑pain — acquisition) → **Pro** (Greeks surface,
  expected‑move cones, IV regime, risk book, the calibration ledger) → **Desk** (multi‑account,
  API, white‑label).
- *Reality check:* retail willingness‑to‑pay has a ceiling and churn is high; conversion will lean
  almost entirely on the **visible track record**. This path only works *because* of calibration.

**B) B2B data / API licensing (highest margin, most durable).**
The cleaned, cross‑index **OI/Greeks/vol‑surface time‑series** and the **calibration data** are
valuable to funds, prop desks, fintechs, and content creators who don't want to build ingestion +
correct Greeks themselves. Sell it as a historical dataset and a real‑time API.
- *Reality check:* this is where the moat compounds — but it requires the dataset to be genuinely
  clean and deep (months→years), and it depends heavily on **data‑licensing terms** (see §7.2).

**C) Personal / prop trading edge (monetize returns, not subscriptions).**
Use the platform yourself (or with a small pool) as a decision‑support edge — calibrated regime
reads, risk‑book scenario/Monte‑Carlo, IV‑crush avoidance. The "product" is the P&L, not the
subscription.
- *Reality check:* highest variance and capital‑dependent; the calibration ledger is what tells you
  whether the edge is real before you size up. Honest backtesting (the lab pillar) is the gate.

**D) Education / community / creator (credibility flywheel).**
The public calibration track record is itself content. A paid community + courses + a credibility
flywheel ("we show our reliability curve") is the cheapest path to acquisition and feeds A.
- *Reality check:* must stay strictly on the **analytics/education** side of the SEBI line (see
  §7.2) — teach method and show calibration, never issue buy/sell calls.

### 7.2 India‑specific realities (read before counting money)
- **SEBI Research Analyst regulation.** Issuing **recommendations** ("buy this option") generally
  requires RA registration and carries liability. The defensible lane is **analytics + education +
  decision‑support**, with probabilistic framing and disclaimers — which is exactly what the
  calibration‑first design is built for. Keep the copilot strictly grounded (no freeform price
  calls).
- **F&O retail loss statistics & tightening rules.** SEBI's own studies show the large majority of
  retail F&O traders lose money, and the regulator has been tightening the segment (lot sizes,
  expiry rationalization). This *helps* a trust‑first, risk‑aware product and *hurts* a
  signal‑selling one — lean into protection and honesty.
- **Data licensing / ToS.** Live chain/OI/Greeks at scale means respecting **NSE/BSE data licensing
  and broker API terms**. A "data product" (path B) is only sellable if the redistribution rights
  are clean — this is a legal question to resolve *before* building the business on it, not after.
- **Account‑data privacy (DPDP).** Reading positions across brokers means handling sensitive
  financial data under India's DPDP Act — consent, storage, and deletion need to be designed in.

### 7.3 Suggested sequence
1. **Build the calibration ledger early** (even on paper forecasts) — it's the trust engine *and*
   the proof you need before charging anyone.
2. **Education/community (D)** first for near‑zero‑CAC acquisition and credibility.
3. **Retail Pro (A)** once the ledger is visibly working and a usable UI exists.
4. **Data/API (B)** once the dataset is deep enough to be worth licensing — the long‑term margin.
5. **Personal/prop (C)** in parallel and privately, as the honest internal validation of the edge
   (and an optional revenue line) — but only after the backtesting lab can prove it.

### 7.4 Cost shape (candid)
Low to start (free/low‑cost data + local compute, no servers in Phase 0), rising with **market‑data
vendor fees** at scale and **LLM inference** once the copilot is live. The variable costs are
data and tokens; the fixed cost is the engineering to keep the calibration honest.

---

## 8. Hard questions & open decisions

The questions I'd want answered before betting on any one path — with my current lean:

**Product / wedge.** What's the one‑line wedge a user repeats to a friend? *(Lean: "it shows its
reliability curve.")* What do they get here they can't assemble free from a broker + ChatGPT?
*(Lean: correct Greeks + a unified risk book + a proven calibration record — none of which a chat
model can fabricate honestly.)*

**Prediction / honesty.** Are outputs probabilities or point calls? *(Probabilities — enforced.)*
Is there a public, time‑stamped track record? *(Designed; not built — build it next.)* How is it
validated — purged/walk‑forward CV, realistic STT/slippage? *(That's the backtesting‑lab mandate.)*

**Data.** Where do chain/OI/IV actually come from at scale, and are the **redistribution rights**
clean enough to sell a data product? *(Open — resolve before path B.)* Is data being stored from
day one? *(Yes — DuckDB/Parquet snapshots already.)*

**AI / copilot.** Reactive chat or proactive? How is every number forced to come from the engine so
the LLM can't hallucinate a price call (and create SEBI exposure)? *(Grounding is a hard
requirement; design before building.)*

**Execution.** Stay analysis‑only, or add assisted (human‑confirmed) execution later? *(v1 is
analysis‑only by decision; revisit only behind explicit gating and the relevant SEBI algo rules.)*

**Compliance.** Where exactly is the analytics‑vs‑advice line drawn, and is a lawyer engaged before
revenue? *(Open — do this before charging.)*

**Moat durability.** What stops a well‑funded competitor copying the screens? *(Only the dataset +
the multi‑year calibration ledger + cross‑broker integration — i.e., time and trust, not code.)*

**Focus.** Which monetization path is the *wedge* vs the *long game*? *(Lean: education+ledger to
earn trust → retail subscription for cash flow → data/API for durable margin.)*

---

## 9. Honest weaknesses of this version

- **Greenfield beyond the core.** Only Phase 0 exists. The forecast/calibration engine, risk book,
  live broker auth, copilot, backtesting lab, and journal are **specified but not built**.
- **No real UI.** A static page only — not consumer‑ready.
- **No live data yet.** Runs on a committed fixture; live Kite/Groww/NSE are designed as drop‑in
  adapters but not wired or hardened.
- **The calibration ledger — the entire thesis — is not yet implemented.** It's the most important
  next thing to build, precisely because everything (trust, monetization) depends on it.
- **Heavy stack deferred.** Postgres/Timescale + Redis, the Next.js frontend, and native (non‑Docker)
  execution are all parked in `docs/PHASE1_BACKLOG.md`.
- **The edge is unproven until the backtester exists.** The honest claim today is "rigorous,
  correct foundation," not "validated trading edge."

---

## 10. Comparison framework (this version filled; the other to be filled in Document 2)

These matrices are deliberately left **half‑filled**: only this version is scored, on its own terms.
Document 2 fills the other column from the other version's dossier, computes the weighted score, and
proposes the merge. (Filling the other column here would defeat the purpose of an unbiased,
standalone write‑up.)

### 10.1 Product & strategy
| Dimension | This version — Options Intelligence Platform | Other version | Merge note |
|---|---|---|---|
| Core identity | Calibrated, probability‑first options analyst; "show the reliability curve" | _(Document 2)_ | Keep the sharper, more defensible wedge |
| Prediction stance | Probabilities/distributions + live calibration; **no accuracy claims** | _(Document 2)_ | Never adopt unverified "high accuracy" |
| Target user | India F&O directional/buyer‑leaning trader first | _(Document 2)_ | Pick the segment with provable willingness‑to‑pay |
| Differentiation / moat | Calibration ledger + cross‑index dataset + cross‑broker risk view | _(Document 2)_ | Merge the strongest moat from each |
| Compliance posture | Analytics/education, probabilistic framing, disclaimers on every surface; analysis‑only v1 | _(Document 2)_ | Adopt the more SEBI‑defensible spine |

### 10.2 Technical & data
| Dimension | This version | Other version | Merge note |
|---|---|---|---|
| Language / stack | Python (numpy/scipy/FastAPI), DuckDB+Parquet+SQLite, Docker/3.12 | _(Document 2)_ | Favor the more maintainable/reproducible base |
| Data sources | Offline‑first `DataSource` protocol; fixture + NSE‑public capture; Kite/Groww planned | _(Document 2)_ | Keep the source with real Greeks+OI; reuse the protocol seam |
| Greeks engine | **Black‑76 on futures**, in‑house, **147 tests** (finite‑diff, parity, vollib agreement, reproducibility) | _(Document 2)_ | Keep validated math; reconcile model choice on futures forward |
| Dealer positioning (GEX/flip) | Planned (flow pillar), not yet built | _(Document 2)_ | Graft whichever has it, validate on NSE |
| Implied distribution | Planned (forecast pillar), not yet built | _(Document 2)_ | Keep whichever has it |
| Risk book / beta‑weighted Greeks | Planned (Phase 1), not yet built | _(Document 2)_ | Keep the more complete one |
| Calibration ledger | Designed as first‑class; not yet built | _(Document 2)_ | **Non‑negotiable** — keep it |
| Time‑series / data moat | DuckDB+Parquet snapshots from day one; deterministic + reproducible | _(Document 2)_ | Keep the one that hoards clean data day 1 |
| Testing / quality | 147 tests, ruff‑clean, adversarially hardened, CI gate | _(Document 2)_ | Adopt the higher test bar |
| Build maturity | Phase‑0 slice built + verified; pillars 1–7 specified | _(Document 2)_ | Use the more complete codebase as the base |

### 10.3 AI, execution, delivery, money
| Dimension | This version | Other version | Merge note |
|---|---|---|---|
| AI / copilot | Specified (grounded, no freeform price calls); not built | _(Document 2)_ | Merge the best agent design; enforce grounding |
| Calibration / transparency | Public reliability curve (designed) | _(Document 2)_ | Non‑negotiable — keep it |
| Execution / trading | **Analysis‑only** in v1 by decision | _(Document 2)_ | Keep the safest gated design |
| Broker integrations | Kite + Groww targeted (offline‑first now) | _(Document 2)_ | Union of integrations |
| Delivery / UX | FastAPI + static page; Next.js deferred | _(Document 2)_ | Adopt whichever has a real UI |
| Monetization | 4 layers on one asset (sub / data‑API / prop / education) | _(Document 2)_ | Merge revenue lines |
| Time‑to‑market | Core correctness done; UI/forecast/calibration pending | _(Document 2)_ | Start from the more shippable base |

### 10.4 Weighted scoring rubric (to be scored in Document 2)
Score each version **1–5** per dimension × weight; the version that wins on **moat + methodology +
maturity** becomes the *base* to build on, with the other's wins grafted in.

| Dimension | Weight | This version | Other version |
|---|---|---|---|
| Defensible moat (data / ledger / network) | 20% | _(Doc 2)_ | _(Doc 2)_ |
| Honest, validated prediction methodology | 15% | _(Doc 2)_ | _(Doc 2)_ |
| Analytics depth (Greeks/OI/GEX/distribution) | 12% | _(Doc 2)_ | _(Doc 2)_ |
| Build maturity / time‑to‑market | 12% | _(Doc 2)_ | _(Doc 2)_ |
| Compliance / SEBI safety | 10% | _(Doc 2)_ | _(Doc 2)_ |
| Monetization clarity & WTP | 10% | _(Doc 2)_ | _(Doc 2)_ |
| AI / copilot quality & grounding | 8% | _(Doc 2)_ | _(Doc 2)_ |
| UX / delivery readiness | 7% | _(Doc 2)_ | _(Doc 2)_ |
| Tech maintainability & scalability | 6% | _(Doc 2)_ | _(Doc 2)_ |
| Cost to build & run | tiebreak | _(Doc 2)_ | _(Doc 2)_ |

### 10.5 Question bank (ask of *each* version)
Wedge & user · prediction honesty & track record · data sources/rights/storage · analytics depth
(Greeks/OI/GEX/distribution/participant‑OI) · AI grounding & SEBI safety · execution stance &
gating · stack/maturity/tests · monetization/pricing/CAC‑LTV/path‑to‑₹1cr‑ARR · compliance line &
DPDP · single points of failure & key risks.

### 10.6 Non‑negotiables that must survive any merge
1. Calibrated, probability‑first outputs with a **live calibration record** — never "accuracy."
2. **In‑house, validated Greeks** (futures‑correct), not a black box.
3. Backtester **bias guards as failing tests**.
4. **Analytics‑not‑advice** compliance spine, disclaimers everywhere.
5. **Hoard clean data from day one** (the dataset is the moat).

---

## 11. What Document 2 will do

After I deliberately read the other version's dossier (and reconcile its claims against its actual
code), Document 2 (`MERGED_BLUEPRINT.md`) will: fill the "other version" columns above, compute the
weighted score, name the **keep / kill / graft** decisions, and produce a **single merged
architecture + roadmap + monetization synthesis** — built on whichever version wins on *moat +
methodology + maturity*, with the other's distinct strengths grafted in, and the §10.6
non‑negotiables enforced throughout.

---

### Appendix — evidence map (this repo)
- Mission & rails: `NORTH_STAR.md`, `PROJECT_SPEC.md`, `CLAUDE.md`
- Quant core: `backend/src/oip/quant/black76.py`, `backend/src/oip/quant/greeks_service.py`
- Data: `backend/src/oip/data/{source,normalize,fixture_replay,nse_public}.py`,
  `data/fixtures/nse_chain_NIFTY_2026-06-12.json`
- Storage: `backend/src/oip/storage/{duck,sqlite_meta,schema.sql}`
- Pipeline/API: `backend/src/oip/pipeline/ingest.py`, `backend/src/oip/api/*`
- Proof: `backend/scripts/demo_phase0.py`
- Tests: `backend/tests/**` (147 passing)
- Decisions & backlog: `docs/decisions/0001‑0006‑*.md`, `docs/PHASE1_BACKLOG.md`
- CI: `.github/workflows/ci.yml`

_End of Document 1. The comparison and merge follow in Document 2, once the other version's dossier
has been read on its own terms._
