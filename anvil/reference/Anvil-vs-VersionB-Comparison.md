# Anvil — Build Dossier & Two-Version Comparison / Merge Framework

> **Purpose of this document.** You've built **two versions of the same idea** (an India options-intelligence product) and want to compare them and merge the best of both into one. This dossier (a) documents **Version A — "Anvil"**, the version I designed and built, in full: my thought process, what exists, my honest read of the idea, the innovations, and how it makes money; and (b) gives you a **comparison framework** — matrices, a weighted scoring rubric, and a question bank — to evaluate **Version B** (your other version) against it, plus a **merge strategy**. Fill in the Version B columns (or hand me Version B and I'll fill them), and we converge on one merged blueprint.

> **How to read it:** Part 1 = everything about Anvil. Part 2 = side-by-side matrices (A filled, B to fill). Part 3 = scoring rubric. Part 4 = the question bank. Part 5 = merge strategy. Part 6 = what I need from you about Version B.

---

## PART 1 — VERSION A: "ANVIL" (the version I built)

### 1.1 My perception of the idea (the honest thesis)

The instinctive pitch — *"connect to my broker, analyse OI + Greeks, and predict the market with high accuracy"* — is half right and half trap. After a 13-agent, fact-checked research sweep, my read is:

- **Raw price prediction is near-impossible to do honestly.** Out-of-sample directional accuracy on liquid Indian indices clusters at **~50–55%**, not 80–90%. Anyone showing more is almost always overfitting, look-ahead bias, or survivorship. Selling "highly accurate predictions" is both a credibility bomb and a **SEBI Research-Analyst liability**.
- **But there IS a real, defensible edge** — not in calling price, but in **fusing three things nobody combines well in India**: (1) **dealer positioning** (GEX / zero-gamma flip / vanna-charm walls), (2) the **market-implied probability distribution** (Breeden-Litzenberger risk-neutral density + expected move), and (3) **your own live positions across brokers** — into one **calibrated regime read**, and then **proving the accuracy publicly** with an immutable track record.
- **The moat is trust + data, not features.** Features get copied in a quarter. A multi-year **public calibration ledger** ("when we say 70%, it happens ~70%"), a **proprietary cleaned OI/Greeks time-series**, and **per-user agent memory** compound and cannot be back-filled.

So Anvil's identity: **an always-on, position-aware AI options analyst that explains every number, fuses dealer flow + implied distribution + your book into a regime read, and earns its "accuracy" claim with a transparent ledger** — analytics/decision-support, not buy/sell calls.

### 1.2 Thought process — the decisions that define Anvil

| Decision | What I chose | Why |
|---|---|---|
| Prediction framing | Calibrated **probabilities / ranges / regime**, accuracy *proven* via a live ledger | Honest, SEBI-defensible, and actually more impressive than a fake hit-rate |
| Data backbone | **Upstox/Dhan** for chain+OI+IV+Greeks; brokers' MCP only to *read positions* | Kite MCP is read-only and has **no chain/Greeks/IV** — a common, fatal misconception |
| Greeks | Computed **in-house** (scipy BSM) | No broker reliably gives Greeks; owning the math = control + a data moat |
| "Beta + gamma" | **Beta-weighted portfolio Greeks** (normalize δ/γ/θ/ν to NIFTY) | Beta isn't a Greek; this is the genuinely useful, rare-in-India feature |
| Execution | **Assisted (human-confirmed) now; auto-exec built but gated OFF** | SEBI algo rules + safety; the order layer is a pluggable seam |
| Wedge | Position-aware fusion + proactive agent + calibration ledger | GEX alone is *not* white space in India anymore (OptionsFlow.in, JustTicks…) |

### 1.3 What already EXISTS (built and verified)

Phase-1 foundation is **built, tested (32/32 passing on Python 3.14), and runs end-to-end offline** (`Stock Market App/anvil/`):

- **Analytics engine (in-house):** `greeks.py` (δ/γ/θ/ν/ρ + IV solver, anchored to closed-form values), `higher_order.py` (vanna/charm/vomma), `oi.py` (buildup matrix, PCR, max-pain, OI walls), `gex.py` (GEX spot²-scaled + explicit dealer sign + **zero-gamma flip**), `implied_dist.py` (Breeden-Litzenberger RND + expected move), `vol.py` (IV rank/skew/term structure/vol cone), `portfolio.py` (**beta-weighted Greeks**), `regime.py` (fused, explainable regime read).
- **Data layer:** pluggable connectors — `demo` (offline synthetic, self-consistent), `upstox`/`dhan` (chain+Greeks+IV+OI), `kite` (positions, read-only, + MCP introspector), `nse_eod` (participant-wise OI / FII-DII / India VIX), `macro`.
- **Execution:** gated layer — `AssistedExecutor` (propose→confirm) live, `AutoExecutor` behind `TRADING_AUTOMATION=OFF`.
- **Store / API / CLI:** DuckDB snapshot store (the moat dataset), FastAPI (`/analyze /gex /implied-dist /portfolio-risk /snapshot`), `anvil pull NIFTY --demo` printing a one-screen regime summary.
- **In-flight (planned, not yet built):** live broker auth — Upstox OAuth (daily token), `growwapi` connector + **gated, dry-run-default** order gateway, Kite login (request_token→checksum→access_token, positions-only).

### 1.4 Architecture (target)

`Data ingestion (Upstox/Dhan/Kite/NSE) → in-house analytics/Greeks engine → model layer (regime/HMM + a validation harness that enforces purged/walk-forward CV, Deflated Sharpe, realistic Indian costs) → Claude agent layer (strict grounding: every number from the engine, no freeform price calls) → delivery (web + Telegram/WhatsApp, vernacular)`. **Moat storage:** cleaned tick-level OI/Greeks/vol-surface time-series + immutable prediction/calibration ledger + per-user memory.

### 1.5 Innovations (what's novel / defensible)

1. **Position-aware regime fusion** — GEX/flip + implied distribution + flow tied to *your* live book, narrated unprompted. (Competitors show GEX; none fuse it with your positions.)
2. **Radical-transparency calibration ledger** — public reliability curve + per-signal driver attribution. Turns "accuracy" from a claim into an auditable asset.
3. **Cross-broker beta-weighted risk cockpit** — net δ/γ/θ/ν normalized to NIFTY across Zerodha+Groww+Upstox. Absent in India.
4. **Retail risk-neutral density** — Breeden-Litzenberger implied distribution as a consumer feature (academic-only in India today).
5. **Proactive agent with memory** — not reactive chat; it watches and reasons. Compliance-as-feature (AI-use disclosure).
6. **Tax-aware live F&O P&L** — STT/turnover/business-income/8-yr-carry-forward inside the analytics.

### 1.6 How Anvil makes money (monetization)

- **Who pays & why:** active F&O retail/prosumers who already pay ₹200–800/mo for analytics (Sensibull/Opstra) but get *no* position-fused, calibrated, proactive layer. Willingness-to-pay rises with proven calibration.
- **Tiers:** Free (chain/OI/PCR/max-pain — acquisition) → **Pro ₹999–2,499/mo** (GEX/flip + implied distribution + beta-weighted cockpit + proactive agent + ledger) → **Desk/institutional** (multi-account, API, white-label).
- **Structural levers (because retail WTP has a ceiling):** **broker rev-share / bundling** (brokers pay for engagement/retention), **affiliate** (account opens), later a **data product** (the cleaned OI/Greeks history) and **API**.
- **The flywheel (the real money engine):** more users → more cleaned data + more logged predictions → better-calibrated, more-trusted ledger → higher conversion & retention → more users. The ledger is both the trust driver *and* the moat.
- **Unit-economics reality:** at ₹999–2,499/mo, ~1,500–4,000 paying Pro users ≈ ₹2–10 cr ARR; bundling + desk tier is what bends the curve. Data costs (Upstox free → TrueData/GDFL ~₹1.4–2.8k/mo/segment) and LLM costs are the main variable spend.

### 1.7 Honest weaknesses of Version A
- Greenfield: live broker auth, the calibration ledger, the agent, and the web/Telegram UX are **not built yet** (only the engine + scaffolds).
- No UI yet (CLI/API only) — not consumer-ready.
- Prediction *models* beyond the rules-based regime read are still to be built and must survive honest validation.
- Depends on daily broker re-auth (no refresh tokens) — an ops wrinkle.
- `growwapi` officially targets Python ≤3.13 vs our 3.14 (handled via optional/lazy import + 3.13-venv fallback).

---

## PART 2 — COMPARISON MATRICES (A filled · B to fill)

> Fill the **Version B** column (or give me B and I'll fill it). "Merge note" = my first instinct for what wins / how to combine.

### 2.1 Product & strategy
| Dimension | Version A — Anvil | Version B (fill) | Merge note |
|---|---|---|---|
| Core identity | Position-aware calibrated regime analyst | ? | Keep the one with a sharper, defensible wedge |
| Prediction stance | Calibrated probabilities + public ledger | ? | Never adopt unverified "high accuracy" claims |
| Target user | F&O retail/prosumer, India-first | ? | Pick the segment with provable WTP |
| Differentiation / moat | Ledger + data flywheel + position fusion | ? | Merge: strongest moat from each |
| Compliance posture | Analytics/education, gated execution | ? | Adopt the more SEBI-defensible spine |

### 2.2 Technical & data
| Dimension | Version A — Anvil | Version B (fill) | Merge note |
|---|---|---|---|
| Language / stack | Python (numpy/scipy/FastAPI/DuckDB) | ? | Favor the more maintainable/hireable stack |
| Data sources (chain/OI/IV/Greeks) | Upstox/Dhan + in-house Greeks | ? | Keep the source with real Greeks+OI |
| Greeks engine | In-house BSM (tested) | ? | Keep validated math; don't trust black boxes |
| Dealer positioning (GEX/flip/walls) | Yes, with explicit conventions | ? | Merge best conventions; validate on NSE |
| Implied distribution | Breeden-Litzenberger RND | ? | Rare — keep whichever has it |
| Beta-weighted portfolio Greeks | Yes | ? | Keep |
| Time-series / data moat | DuckDB→Timescale, snapshots | ? | Keep the one that starts hoarding data day 1 |
| Architecture / scalability | Modular connectors + engine + agent | ? | Merge cleanest module boundaries |
| Testing / quality | 32 tests green, offline-runnable | ? | Adopt the higher test bar |
| Build maturity (what exists) | Engine+store+API+CLI built | ? | Reuse the more complete codebase as the base |

### 2.3 AI, execution, delivery, money
| Dimension | Version A — Anvil | Version B (fill) | Merge note |
|---|---|---|---|
| AI / agent layer | Proactive, grounded, memory (planned) | ? | Merge best agent design; enforce grounding |
| Calibration / transparency | Public ledger (planned) | ? | Non-negotiable — keep it |
| Execution / trading | Assisted now, auto gated OFF | ? | Keep the safest gated design |
| Broker integrations | Upstox+Dhan+Kite+Groww | ? | Union of integrations |
| Delivery / UX | CLI+API now; web/Telegram later | ? | Adopt whichever has real UI |
| Monetization model | Tiers + broker rev-share + data | ? | Merge revenue lines |
| Pricing | Free / ₹999–2,499 / desk | ? | Reconcile to one ladder |
| Time-to-market | Engine done; UI/auth pending | ? | Start from the more shippable base |
| Cost to run | Low (free data + scipy) → scales | ? | Prefer lower variable cost |

---

## PART 3 — WEIGHTED SCORING RUBRIC

Score each version **1–5** per dimension; multiply by weight; sum. (Weights are my suggestion — adjust to your priorities.)

| Dimension | Weight | A score | B score |
|---|---|---|---|
| Defensible moat (data/ledger/network) | 20% | | |
| Honest, validated prediction methodology | 15% | | |
| Analytics depth (GEX/dist/Greeks/OI) | 12% | | |
| Build maturity / time-to-market | 12% | | |
| Compliance / SEBI safety | 10% | | |
| Monetization clarity & WTP | 10% | | |
| AI/agent quality & grounding | 8% | | |
| UX / delivery readiness | 7% | | |
| Tech maintainability & scalability | 6% | | |
| Cost to build & run | — (tiebreak) | | |
| **Weighted total** | 100% | | |

> Rule of thumb: if one version wins on **moat + methodology + maturity** (the top 3), it should be the **base** you build on; graft the other's wins in.

---

## PART 4 — QUESTION BANK (ask this of EACH version)

**Product / positioning:** What's the one-line wedge? Who is the user and what do they pay today? What do they get here that they can't get free from Kite-MCP + ChatGPT? What's the 12-month moat?

**Prediction / honesty:** Are outputs probabilities or point calls? Is there a *public, time-stamped* track record? How is it validated (walk-forward? purged CV? realistic STT/slippage)? What's the claimed accuracy and is it provable?

**Data:** Where do chain/OI/IV/Greeks actually come from? Real-time or EOD? Are Greeks computed or vendor-supplied? Is data being *stored* from day one (the moat)? What does data cost at scale?

**Analytics depth:** GEX/zero-gamma flip? Vanna/charm? Implied distribution? Beta-weighted portfolio Greeks? Participant-wise OI / FII-DII? Vol surface?

**AI / agent:** Reactive chat or proactive? Memory of the user? Is every number grounded in the engine, or can the LLM hallucinate a price call? What stops a buy/sell recommendation slipping out (SEBI)?

**Execution:** Read-only, assisted, or auto? How are real-money orders gated/confirmed? Algo-compliance plan?

**Tech / maturity:** Language/stack? What actually runs today vs slideware? Test coverage? Scalability path? Who can maintain it?

**Monetization:** Pricing tiers? Broker rev-share? CAC/LTV assumptions? Path to ₹1cr ARR? What's the data/API upside?

**Compliance:** Analytics-vs-advice line? Disclaimers? AI-use disclosure? DPDP for holdings? Lawyer engaged?

**Risk:** Single points of failure? Dependence on one broker/data source? Regulatory exposure? Key-person/tech risk?

---

## PART 5 — MERGE STRATEGY

**Principle:** one version becomes the **base codebase**; the other contributes **specific, high-value grafts**. Don't 50/50 blend — that doubles the bugs.

**Decision flow:**
1. Score both (Part 3). The winner on **moat + methodology + maturity** is the base.
2. List Version B's distinct strengths (a feature, a data source, a UI, a monetization line, a better agent design). Each becomes a graft onto the base.
3. Resolve conflicts with the **non-negotiables** (these come from A's research and should survive any merge): *honest/calibrated prediction framing, in-house validated Greeks, gated execution, analytics-not-advice compliance, data hoarded from day one.*
4. Produce a single **Merged v1 blueprint** = base architecture + grafted wins + one roadmap.

**My prior (pending Version B):** Anvil's **engine, calibration ledger, compliance spine, and data moat** are strong foundations to keep; the most likely things to graft from a second version are **UI/UX, a slicker agent/chat experience, additional broker or data integrations, or a monetization/go-to-market angle** I haven't covered. I'll confirm once I see B.

---

## PART 6 — WHAT I NEED FROM YOU ABOUT VERSION B

To fill the matrices, score, and produce the merged blueprint, share whatever exists for Version B:
- A description / pitch (or its README/spec), and **what actually runs** today.
- Its **stack/language**, data sources, and whether Greeks/GEX/implied-distribution exist.
- Its **AI/agent** approach, **execution** stance, **UI/delivery**, and **monetization/pricing**.
- Anything you think it does **better** than Anvil (so I weight the grafts right).
- The repo/files if you want me to read it directly.

---

## Next step (on approval)
1. Save this dossier into your project as `anvil/Anvil-vs-VersionB-Comparison.md` (standalone, openable).
2. You share Version B (Part 6); I fill the Version B columns, compute the weighted comparison, and deliver the **Merged v1 blueprint**.
3. Resume the live-connector build on the merged base.
