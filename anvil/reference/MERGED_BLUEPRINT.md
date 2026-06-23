# Merged Blueprint — Brutal Audit, the Best Version, and the Monetization‑First Build

> **Document 2.** This is the side‑by‑side audit and the merge decision, written after reading
> *both* dossiers (`COMPARISON_AND_MERGE.md` for the Options Intelligence Platform, and
> `Anvil-vs-VersionB-Comparison.md` for Anvil) **and** both codebases directly. I built one of these
> and read the other's source line by line, so this audit grades **claims against code**, not
> marketing against marketing. It is deliberately blunt about *both* — including the version I built.
>
> _Author: Claude (Claude Code). Date: 2026‑06‑18. For: you. Lead wedge chosen: **trust + breadth**._
>
> **Naming used here:** **OIP** = Options Intelligence Platform (`Stock Market App - claude.ai/`).
> **Anvil** = the other version (`Stock Market App/anvil/`).

---

## 0. TL;DR — the verdict

**Build the merged product on the OIP spine. Graft Anvil's analytics breadth onto it. Then build the
thing *neither* has and which is the entire moat: the calibration ledger.**

- **Base = OIP** — because the product's whole reason to exist is *trustworthy calibration*, and you
  cannot build a credible "we show our reliability curve" product on an under‑tested,
  spot‑approximated engine. OIP is the disciplined spine (futures‑correct Black‑76, 147 tests,
  reproducible storage, offline‑first, ADRs, CI). **Discipline is expensive to retrofit; features
  are cheap to port.**
- **Graft from Anvil** — its already‑built analytics (GEX + zero‑gamma flip, implied‑distribution/
  RND, IV regime, vol surface, OI analytics, beta‑weighted risk book, higher‑order Greeks), plus its
  *design patterns* (gated execution seam, multi‑broker connector interface, multi‑index config,
  CLI). Re‑ground every ported module on the **futures price** (Black‑76) — which also *fixes* a
  latent correctness issue they carry today.
- **Then build the moat both lack** — the **calibration ledger** + an **honest backtesting lab**,
  then a **real UI**, **live data**, and a **grounded copilot**.
- **Honesty up front (this matters):** on the generic weighted rubric, **Anvil actually scores
  slightly higher today (≈3.0 vs ≈2.8)** — because it has more *built*. I am still choosing OIP as
  the base, and §4 explains exactly why that raw total is misleading for a trust product. A brutal
  auditor shows the number that argues against their own recommendation, then beats it on the merits.

---

## 1. Brutal audit — Anvil (claims vs code)

**What is real and genuinely good (verified in code):**
- A broad, modular analytics engine that OIP does **not** have: `engine/gex.py` (GEX, spot²‑scaled,
  explicit dealer sign, **zero‑gamma flip** via grid scan + linear interpolation),
  `engine/implied_dist.py` (risk‑neutral density + expected move), `engine/oi.py` (PCR, max‑pain,
  OI walls, buildup matrix), `engine/vol.py`, `engine/regime.py`, `engine/portfolio.py`
  (beta‑weighted Greeks), `engine/higher_order.py` (vanna/charm/vomma).
- A **gated execution seam** done responsibly: `execution/gateway.py` — `AssistedExecutor`
  (propose→confirm) live, `AutoExecutor` refusing to act unless `TRADING_AUTOMATION` is on (with an
  explicit SEBI‑empanelment note). This is more product‑complete than OIP's analysis‑only stance.
- **Multi‑index from day one** (`config.py`: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50,
  SENSEX, BANKEX, with lot sizes + strike steps), a DuckDB snapshot store, a FastAPI surface, a
  pluggable connector interface, and a CLI. Genuinely the broader **product surface**.

**What is overstated, or claimed but not in the code (brutal):**
- **"Tax‑aware live F&O P&L (STT / turnover / business‑income / 8‑yr carry‑forward)"** is listed as a
  *shipped innovation* (#6). **There is no tax module in the tree.** It's a roadmap idea presented as
  built.
- **"Proactive agent with memory"** (#5) and the **calibration ledger** (#2) — the two most important
  differentiators — are **not built** (the dossier admits this elsewhere, but lists them as
  innovations). The ledger is the whole moat and it is vapor in *both* versions.
- **"Multi‑broker"** is design‑stage: `ingest/upstox.py`, `dhan.py`, `kite.py`, `nse_eod.py`,
  `macro.py` exist as files, but only the offline **`demo`** source runs without credentials; live
  auth (Upstox OAuth, growwapi, Kite login) is admitted in‑flight. "Union of integrations" today
  means "interfaces + stubs," not working connections.
- **Test count "32/32"** with light coverage: `tests/test_greeks.py` is ~7 assertions (one ATM price,
  parity, reference Greeks, gamma call=put, IV round‑trip). There are **no finite‑difference
  cross‑checks, no third‑party engine agreement, and no reproducibility test.** Breadth outran
  verification.

**The correctness issue under the whole surface:**
- The engine is **Black‑Scholes‑Merton on *spot*** with an assumed dividend yield `q = 0.012`
  (`engine/greeks.py`, `compute_greeks(... S ... q ...)`). Indian index options are **futures‑
  settled**; the correct model is **Black‑76 on the actual future**. BSM‑with‑q only *approximates*
  the forward as `S·e^{(r−q)T}`, which ignores the real futures basis (carry, demand/supply,
  sentiment — not just dividends). Because GEX, the implied distribution, regime, and the portfolio
  Greeks all call this engine on `spot`, **the entire analytics surface inherits a spot‑based
  approximation.** Anvil's own `gex.py` even warns in‑comment: *"validate sign and level on real NSE
  data before trusting; US results do not transfer."* The headline feature is, by its own
  admission, **unvalidated on Indian data.**

**Net on Anvil:** impressive *breadth*, shipped fast, with the right instincts (calibration framing,
gated execution, in‑house Greeks, data‑as‑moat). But it is **broad and lightly verified, built on a
less‑correct underlying**, and several of its marquee claims are aspirational.

---

## 2. Brutal audit — OIP (claims vs code, no self‑flattery)

**What is real and genuinely good (verified — I built it and the suite proves it):**
- **Black‑76 on the futures price** (`backend/src/oip/quant/black76.py`) — futures‑correct for Indian
  index options, with the futures‑price *source* tagged and auditable (`nse_futures` vs a derived,
  clearly‑labelled cost‑of‑carry forward).
- **147 tests** across **four independent** validation strategies: known closed‑form values vs an
  independent SciPy reference, put‑call parity across a grid, **finite‑difference cross‑checks of
  every Greek**, and **third‑party agreement** with `vollib` — plus IV round‑trip, edge‑case guards,
  and a **reproducibility** test (stored Greeks re‑read bit‑for‑bit).
- **Discipline that is hard to retrofit:** offline‑first `DataSource` protocol, deterministic +
  reproducible DuckDB+Parquet+SQLite storage, six ADRs, a CI gate, Docker/Python‑3.12
  reproducibility, an adversarial multi‑agent hardening pass (11 fixes), disclaimers on every
  surface.

**Brutal weakness — it is *narrow* (as a product, it's behind Anvil):**
- It computes a **chain + Greeks** and serves them. That's it. **None** of the things people actually
  pay for exist yet: no GEX/zero‑gamma, no implied distribution, no regime, no vol surface, no OI
  analytics, no risk book. No calibration ledger (the thesis!). No live data. No UI beyond a static
  page. No copilot. No execution. Multi‑index is *seeded* (NIFTY/BANKNIFTY) but the breadth isn't
  there.
- **As a thing you could sell next month, OIP is *less* ready than Anvil.** Its value is entirely in
  the quality of its foundation, not its surface area.

**Shared truth (the part that should scare you about *both*):** neither version has the **calibration
ledger**, a **real UI**, a **grounded copilot**, or **working live data**. Both are **pre‑product.**
The single most valuable, most defensible component — the public reliability curve — **does not exist
anywhere yet.** Whoever builds it first, on a trustworthy engine, wins.

---

## 3. Filled comparison matrices

### 3.1 Product & strategy
| Dimension | OIP | Anvil | Merge decision |
|---|---|---|---|
| Core identity | Calibrated, probability‑first analyst; "show the reliability curve" | Position‑aware calibrated regime analyst | **Same thesis.** Keep it; it's correct and defensible. |
| Prediction stance | Probabilities + live calibration; no accuracy claims | Calibrated probabilities + public ledger | Identical. Non‑negotiable in both. |
| Target user | India F&O buyer‑leaning trader | India F&O retail/prosumer | Converge — retail/prosumer, buyer‑first. |
| Differentiation / moat | Calibration ledger + cross‑index dataset + cross‑broker view (planned) | Ledger + data flywheel + position fusion (planned) | Same moat; **neither built it.** Build it (M2). |
| Compliance posture | Analytics/education, disclaimers, analysis‑only | Analytics/education, **gated execution seam built** | Adopt Anvil's gated execution design; keep OIP's disclaimer rigor. |

### 3.2 Technical & data
| Dimension | OIP | Anvil | Merge decision |
|---|---|---|---|
| Stack | Python/FastAPI, DuckDB+Parquet+SQLite, Docker/3.12 | Python/FastAPI, DuckDB, structlog, CLI | Same family. **OIP's reproducible runtime + tests is the base.** |
| Greeks engine | **Black‑76 on futures**, 147 tests | BSM‑on‑spot+q, ~32 light tests | **Keep OIP's engine.** It's the correct model and verified. |
| Higher‑order Greeks | ✗ | ✓ vanna/charm/vomma | **Graft from Anvil** (re‑ground on Black‑76). |
| GEX / zero‑gamma flip | ✗ | ✓ (flagged: validate on NSE) | **Graft**; validate on NSE fixtures, label honestly. |
| Implied distribution / RND | ✗ | ✓ | **Graft.** |
| IV regime / vol surface | ✗ | ✓ | **Graft.** |
| OI analytics (PCR/max‑pain/walls) | ✗ | ✓ | **Graft.** |
| Beta‑weighted risk book | ✗ (planned) | ✓ | **Graft** (this is OIP's "Phase 1" — Anvil already did it). |
| Data sources | Offline‑first protocol; fixture + NSE capture; Kite/Groww planned | demo + Upstox/Dhan/Kite/NSE stubs | **Keep OIP's protocol;** adopt Anvil's connector *interface* + the union of brokers. |
| Time‑series / data moat | DuckDB+Parquet, deterministic + reproducible | DuckDB snapshot store | **Keep OIP's** (reproducible substrate for a credible ledger). |
| Multi‑index | Seeded (2) | ✓ (7 indices) | **Adopt Anvil's multi‑index config.** |
| Testing / quality | **147, multi‑strategy, hardened, CI** | ~32, light | **OIP's bar wins.** Everything ported must meet it. |
| Build maturity (surface) | Narrow | Broad | Anvil's surface is the graft list. |

### 3.3 AI, execution, delivery, money
| Dimension | OIP | Anvil | Merge decision |
|---|---|---|---|
| AI / copilot | Specified, grounded; not built | Proactive + memory; not built | Build once; enforce strict grounding (no freeform price calls). |
| Calibration ledger | Designed; not built | Claimed; not built | **Build it — M2. The moat.** |
| Execution | Analysis‑only | Assisted live / Auto gated OFF | **Adopt Anvil's gated seam;** keep OFF until SEBI algo empanelment. |
| Broker integrations | Kite + Groww (offline now) | Upstox + Dhan + Kite + (Groww) | **Union**, behind OIP's `DataSource` protocol. |
| Delivery / UX | Static page + API | CLI + API | Neither is enough — **build a real UI (M3).** |
| Monetization | 4 paths tied to the multi‑index asset | Tiers + broker rev‑share + data; concrete unit‑economics | **Merge:** OIP's asset framing + Anvil's pricing/unit‑economics thinking. |

---

## 4. Weighted scorecard — and why the raw total doesn't decide it

Scored 1–5 (my assessment, claims‑vs‑code), using the dossier's suggested weights.

| Dimension | Weight | OIP | Anvil |
|---|---|---|---|
| Defensible moat (data/ledger/network) | 20% | 3 | 3 |
| Honest, validated prediction methodology | 15% | **4** | 2 |
| Analytics depth (GEX/dist/Greeks/OI) | 12% | 1 | **4** |
| Build maturity / time‑to‑market | 12% | 2 | **3** |
| Compliance / SEBI safety | 10% | 4 | 4 |
| Monetization clarity & WTP | 10% | 3 | **4** |
| AI/agent quality & grounding | 8% | 2 | 2 |
| UX / delivery readiness | 7% | 2 | 2 |
| Tech maintainability & scalability | 6% | **4** | 3 |
| **Weighted total** | 100% | **2.80** | **3.02** |

**Anvil wins the naive total (3.02 vs 2.80).** I'm still choosing **OIP as the base.** Here's the
brutal reasoning, because this is the crux of the whole decision:

1. **~80% of Anvil's lead comes from "analytics depth" + "maturity" — both of which are *portable
   breadth*, not moat.** You can graft eight analytics modules in weeks. You **cannot** graft a
   futures‑correct, 147‑test, reproducible engine and the discipline that produced it into a
   codebase after the fact — you'd have to rebuild it. The score rewards the cheap‑to‑copy axis and
   under‑rewards the expensive‑to‑build axis.
2. **The product has exactly one existential failure mode: shipping numbers you can't stand behind.**
   A *calibration* product that is itself miscalibrated or subtly wrong is self‑refuting — it
   destroys the only asset (trust). The dimensions that prevent that — **methodology and
   maintainability — are precisely where OIP wins**, and a generic rubric under‑weights them for
   this specific business.
3. **The graft direction also *fixes* Anvil.** Porting its modules onto Black‑76‑on‑futures corrects
   the spot‑approximation they currently inherit. So choosing OIP as the base doesn't just relocate
   features — it improves them.
4. **Base choice should be decided by "whose DNA do you want," because the hardest remaining work is
   shared.** Ledger, UI, copilot, and live data must be built regardless of base. Given that, inherit
   the **disciplined** DNA.

**Rule‑of‑thumb cross‑check (top‑three: moat + methodology + maturity):** moat is a tie; methodology
→ OIP; maturity → Anvil. Not decisive alone — so the tiebreak is the reasoning above. **Base = OIP.**

---

## 5. Keep / Kill / Graft

| From | KEEP (base) | GRAFT (port in) | KILL / DON'T CARRY |
|---|---|---|---|
| **OIP** | Black‑76 engine; offline‑first `DataSource`; reproducible DuckDB+Parquet+SQLite; test‑first + CI; ADRs; disclaimers; the calibration‑first data discipline | — | The "analysis‑only forever" stance (relax to *gated* execution later) |
| **Anvil** | — | GEX + zero‑gamma flip; implied‑distribution/RND; IV regime; vol surface; OI analytics; beta‑weighted risk book; higher‑order Greeks; gated execution seam; multi‑broker connector *interface*; multi‑index config; CLI | **BSM‑on‑spot engine** (replace with Black‑76); the **unbuilt** "tax‑aware P&L" and "agent memory" *as claims* (build them honestly later, don't inherit the claim); light test suite (re‑write to OIP's bar on port) |
| **Neither (build new)** | — | **Calibration ledger** + honest backtesting lab; **real UI**; **grounded copilot**; live broker auth | — |

---

## 6. The merged architecture

```
                ┌───────────────────────────────────────────────┐
   Delivery     │  Next.js UI  ·  Grounded Copilot  ·  CLI        │   ← M3, M5
                └───────────────▲───────────────────────────────-┘
                                │ REST / WS
                ┌───────────────┴───────────────────────────────┐
   API          │  FastAPI: chain · greeks · gex · implied-dist  │
                │          regime · risk-book · CALIBRATION       │   ← ledger surface = the headline
                └───┬───────────────┬───────────────┬───────────┘
                    │               │               │
   Moat layer   ┌───▼─────────┐ ┌───▼──────────┐ ┌──▼───────────────┐
   (build new)  │ Calibration │ │ Honest       │ │ Event / regime    │   ← M2
                │ ledger      │ │ backtest lab │ │ intelligence      │
                │ (Brier/RD)  │ │ (bias=tests) │ │                   │
                └───┬─────────┘ └───┬──────────┘ └──┬───────────────┘
                    │               │               │
   Analytics    ┌───▼───────────────▼───────────────▼───────────────┐
   (graft from  │ GEX/flip · implied-dist · regime · vol surface ·   │   ← M1 (ported onto Black-76)
    Anvil)      │ OI analytics · beta-weighted risk book · higher-Δ  │
                └───────────────────────▲───────────────────────────┘
                                         │  computes on the FUTURE (F)
   Engine       ┌─────────────────────── ┴──────────────────────────┐
   (OIP base)   │ Black-76 Greeks engine (futures price, 147 tests)  │
                └───────────────────────▲───────────────────────────┘
                                         │
   Data         ┌───────────────────────┴───────────────────────────┐
   (OIP proto + │ DataSource protocol → fixture · NSE · Upstox/Dhan  │   ← M4 (live)
    Anvil       │ · Kite/Groww (positions)   |  multi-index (7)       │
    connectors) └───────────────────────▲───────────────────────────┘
                                         │
   Storage      ┌───────────────────────┴───────────────────────────┐
   (OIP)        │ DuckDB+Parquet (snapshots, greeks, FORECASTS,       │   ← the moat dataset,
                │ OUTCOMES) + SQLite registry  → Postgres/TS at scale │      reproducible from day 1
                └────────────────────────────────────────────────────┘
```

**The one rule that makes this merge coherent:** every analytic computes on the **futures price via
the Black‑76 engine**, and **every forecast it implies is written to the ledger and later scored
against the realized outcome.** Breadth feeds the ledger; the ledger proves the breadth is honest.

---

## 7. Monetization‑sequenced roadmap (lead = trust + breadth)

Each phase is chosen to **raise the value of the one asset** — *deep multi‑index analysis + the
calibration dataset* — and to unlock specific revenue. The order maximizes the **overall** ceiling,
per your "trust + breadth" choice, not the fastest single rupee.

| Phase | What ships | Why it makes money | Revenue path it unlocks |
|---|---|---|---|
| **M1 — Breadth on a correct base** | Port OI, vol surface, implied‑distribution, GEX/flip, regime, beta‑weighted risk book, higher‑order Greeks onto Black‑76; **all 7 indices**; test‑first | The visible analytics people actually pay for — now futures‑correct and across every index | Foundation for A (retail) + B (data) |
| **M2 — The moat: calibration ledger + honest backtest lab** | Forecast→outcome scoring (Brier/log‑loss/reliability/coverage) per index/horizon/regime; bias‑guards‑as‑failing‑tests; public reliability surface | Turns "accuracy" into an **auditable asset**; the thing no competitor can fake or back‑fill | D (education/credibility) + retention for A |
| **M3 — Real UI** | Next.js dashboard: chain+Greeks, GEX/flip, expected‑move cone, regime, risk book, **the reliability curve** | Makes it usable and demoable; the reliability curve is the hook | A (retail subscription) |
| **M4 — Live data** | Wire Upstox/Dhan (chain/OI/IV) + Kite/Groww (positions) + NSE participant OI behind the `DataSource` protocol; harden | Real‑time + position‑aware = the prosumer upgrade; starts the data flywheel for real | A (Pro) + B (data) |
| **M5 — Grounded copilot** | Claude API, tool‑use **strictly** over engine endpoints, per‑user memory | Higher willingness‑to‑pay and stickiness; "ask your book" | A (Pro/Desk) |
| **M6 — Monetization activation** | Education + reliability‑curve content → retail Pro tiers → data/API → private prop validation; adopt gated execution only behind SEBI algo rules | Converts the asset into revenue across all four paths, in risk order | A → B → D → C |

**India gating preconditions (resolve *before* the revenue they gate):**
- **SEBI Research‑Analyst line** — stay analytics/education/decision‑support; never issue buy/sell
  calls; keep the copilot grounded. Get a lawyer before charging (gates A, D, C).
- **NSE/BSE + broker data‑licensing / ToS** — clean redistribution rights are a hard precondition for
  the **data product** (gates B).
- **DPDP (account data)** — consent/storage/deletion designed in before reading positions (gates the
  position‑aware features in M4+).
- **SEBI algo‑execution empanelment** — required before *any* automated order placement (gates the
  `AutoExecutor`; assisted/confirm is the near‑term ceiling).

**Cost shape:** low through M1–M3 (free/cheap data + local compute), rising with **market‑data vendor
fees** (M4) and **LLM inference** (M5). Variable cost = data + tokens; fixed cost = the engineering
to keep calibration honest.

---

## 8. Risks & what could make this verdict wrong

- **Speed cost.** OIP‑as‑base means *porting* Anvil's breadth (re‑grounding on Black‑76 + writing
  tests) instead of just hardening Anvil. If your dominant goal were "fastest demoable surface,"
  Anvil‑as‑base would win — but you chose trust + breadth, where defensibility beats speed.
- **GEX/regime are unproven on NSE.** Anvil's own comments say so. We port them but treat their
  *levels/signs* as hypotheses to validate against NSE history in the backtest lab — not as truth.
  Shipping an unvalidated GEX signal as if it were calibrated would violate the core thesis.
- **The ledger needs months of data to be credible.** The moat is real but **slow**; the reliability
  curve isn't persuasive until it has a track record. Start logging forecasts *now* (even on the
  offline fixture / paper forecasts) so the clock starts early.
- **Regulatory / data‑rights surprises** could constrain the data product (B) or the copilot. Treat
  §7's gating items as real blockers, not footnotes.
- **Single‑builder / key‑person risk** and **daily broker re‑auth** (no refresh tokens) are real ops
  wrinkles for M4+.

---

## 9. Build increment 1 — concrete spec (on approval, a separate pass)

Start of **M1** + seed of **M2**, all on the OIP base, test‑first to the 147‑test bar:

1. **Multi‑index support** — extend `backend/src/oip/config.py` with lot sizes + strike steps for
   NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50/SENSEX/BANKEX; add per‑index fixtures under
   `data/fixtures/`.
2. **New analytics package `backend/src/oip/analytics/`** — port, re‑grounded on the **future** via
   the existing Black‑76 engine (`oip.quant.black76` / `greeks_service`):
   - `oi.py` (PCR, max‑pain, OI walls, buildup) · `vol.py` (IV rank/percentile, skew, term
     structure) · `implied_dist.py` (RND + expected‑move cone) · `gex.py` (GEX + zero‑gamma flip).
   - Each with `backend/tests/analytics/test_*.py`: known‑value/finite‑difference where applicable;
     GEX validated against an NSE‑shaped fixture and **explicitly labelled "needs live NSE
     validation."**
3. **Calibration ledger seed `backend/src/oip/calibration/`** — `ledger.py` (append‑only
   forecast + realized‑outcome records in DuckDB/Parquet, reproducible) and `scoring.py`
   (Brier, log‑loss, reliability bins, band coverage), with `backend/tests/calibration/test_*.py`
   (known‑value scoring checks). No UI yet — the data model + math first, because everything else
   hangs off it.
4. **Wire into the pipeline/API** — extend the analyze path and add `/analytics/{underlying}` +
   `/calibration` endpoints, every response keeping the disclaimer.

Deliverable of that pass: the merged repo computes **deep analytics across all indices on a
futures‑correct, tested engine, and starts logging forecasts for calibration** — i.e., the
trust + breadth foundation, in code, verified.

---

## 10. Decision & next step

- **Decision:** merge onto the **OIP base**, graft Anvil's analytics + patterns (re‑grounded on
  Black‑76), build the calibration ledger as the moat, sequence M1→M6 for maximum overall
  monetization. The §6 non‑negotiables (calibrated outputs, in‑house validated Greeks, bias‑guards
  as failing tests, analytics‑not‑advice, hoard data day 1) hold throughout.
- **Next step (your call):** approve, and I execute **increment 1** (§9) as a separate build pass —
  or adjust the increment scope first.

_End of Document 2._
