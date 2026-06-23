# Anvil — Real-Time Simulation: Findings & Plan (report-back before heavy build)

*Prepared 22 Jun 2026, ~10:20 IST (markets open). Read-only exploration only — no trades, no orders, nothing that moves money.*

---

## TL;DR

- **Your product is "Anvil" — an India options-intelligence engine** (FastAPI backend + React/Vite PWA), whose pitch is *calibrated probabilities you can audit*, not accuracy claims.
- **The Upstox live feed already works.** Your access token is an **extended token valid to 19 Jun 2027** (not the usual daily token), and I pulled **live NIFTY / BANKNIFTY / SENSEX chains with Greeks right now**. Nothing is blocking real-time index data — no device login needed.
- **The "simulation that already exists"** is the `anvil/paper` + `anvil/live` paper-trading engine. It is sophisticated but runs on **synthetic replay or a "frozen-smile" real-day replay — not a true live stream**, and it's **options-strategy P&L**, not index/stock *prediction*. That's the gap your new sim fills.
- **How it's performing (honest read):** the resolved track record (775 forecasts) is **systematically over-confident** — it says 68.8% when 55.9% actually happens (Brier 0.253). The *live* track record is essentially not yet accrued (11 live forecasts). This is fixable with recalibration + live logging, and it's exactly why the calibration-first framing matters.
- **I built + ran the first piece of the new sim** (`realtime_sim/live_index_forecast.py`) against your live feed. It works.
- **Two things need your decision** (below): the **monetization U-turn** (your own backlog says monetization is OFF) and **what "my product / performance" should track**.
- **One security flag:** your real Upstox API key + secret are pasted into `.env.example`, which **is committed to git**. Rotate + scrub.

---

## 1. What the existing app and simulation actually are

**The app — "Anvil, Options Intelligence for Indian Markets."** A personal, multi-device PWA (React + Vite) over a FastAPI backend. Greeks are computed in-house with **Black-76 on the futures price** (correct for Indian index options, which settle off futures), so it never depends on a broker for Greeks. The product's whole identity is *calibration over accuracy*: every forecast is shown as a probability with a **public reliability curve** and a single "Calibration Score" ("when we say 70%, it happens ~70% of the time"). Data sources: **Upstox** (primary live chain + Greeks + IV + OI), Dhan (fallback), Kite/Groww (positions, read-only), NSE/BSE bhavcopy + Yahoo for history. It's a mature codebase — ~150 Python modules, a calibration ledger (DuckDB), a backtester with look-ahead/survivorship guards enforced as failing tests.

**The existing simulation** lives in `anvil/paper/` (the account) and `anvil/live/` (the loop). `PaperBook` is a real paper-trading account: exact cash accounting, India F&O charge schedule (STT/GST/stamp/SEBI), SPAN-lite margin, a drawdown kill-switch, and a full performance scorecard (win rate, profit factor, expectancy, Sharpe/Sortino, attribution). `RealtimeEngine.run_tick()` marks positions → trips the kill-switch → manages exits → generates option-strategy candidates → opens the top-ranked through a Risk Governor → logs conviction to the calibration ledger.

**But two limitations make it the *wrong* base for what you're asking:**

1. **It isn't truly real-time.** The engine is driven by `ReplaySource` (a **seeded synthetic** path) or `RealDaySource` (snapshots the real chain once, then walks the real intraday path under a **frozen IV smile**). The code's own docstring says the live driver is *"Phase 3b"* — i.e. **not built yet**. `eventbus.py` notes the Upstox WebSocket V3 feed is *"wired when keys are present"* — it currently **polls REST**, it does not stream.
2. **It predicts strategy P&L, not the market.** It answers *"how would this options structure have done,"* not *"where is the index / this stock going."*

So a **new** real-time index & stock *prediction* simulation is genuinely distinct, not a re-skin.

---

## 2. What "my product" most likely means (and the one thing to confirm)

Best interpretation: **"my product" = the Anvil engine itself, and "how is it performing in real time" = its prediction track record** — i.e. are the probabilities it emits actually calibrated against live outcomes, plus the paper-strategy equity curve.

I checked the calibration ledger so this isn't a guess. Resolved forecasts (Sep–Nov 2025 backtest sample, n=775):

| Predicted band | n | Model said | Actually happened |
|---|---|---|---|
| 40–60% | 53 | 57.3% | **41.5%** |
| 60–80% | 578 | 64.0% | **51.9%** |
| 80–100% | 144 | 92.6% | **77.1%** |
| **All** | **775** | **68.8%** | **55.9%** (Brier 0.253) |

Read honestly: **the current model is over-confident in every bucket** (by 12–16 points), and Brier 0.253 is only marginally better than a coin-flip baseline. That's not a failure — it's the calibration layer doing its job and telling you the truth. It's correctable with isotonic/Platt recalibration and, more importantly, by **accruing a real *live* track record** (right now there are only 11 live-sourced forecasts; 246 forecasts sit open/unresolved). The new sim should make live logging + resolution automatic.

**Confirm for me:** by "my product's performance" do you mean (a) this **forecast calibration / track record**, (b) the **paper-trading account P&L**, or (c) your **actual broker holdings** (Kite/Groww positions)? I found no specific named portfolio in the repo; if you mean (c), note your **Groww token expired this morning (~06:00 IST)** and Kite isn't authenticated, so real-holdings P&L would need a device login. Upstox (market data) is the one that's live.

---

## 3. Upstox live connection — exact status

**Status: CONNECTED and working. No action needed for live market data.**

- `ANVIL_PRIMARY_SOURCE=upstox`; a full OAuth flow exists (`auth/upstox_auth.py`) plus an encrypted token store and a clean REST connector (`ingest/upstox.py`) covering NSE **and** BSE indices.
- The cached `UPSTOX_ACCESS_TOKEN` is an **extended token** (`isExtended: true`, user `5WC3LA`) that **expires 19 Jun 2027** — so the usual "token dies at 03:30 IST daily, needs interactive re-login" problem **does not apply here**. This is the key reason I could proceed without your device.
- I called the live API just now (10:15–10:20 IST) and got 200s with real data:
  - **NIFTY 24,150.9** · exp 23 Jun · ATM 24150 · IV ~14% · straddle 156
  - **BANKNIFTY 57,817** · exp 30 Jun · IV ~13.7%
  - **SENSEX 77,242** · exp 25 Jun · IV ~14%
- One gotcha I solved: Upstox is behind Cloudflare, which **403s the default Python user-agent** ("Error 1010"). Sending a browser User-Agent fixes it — baked into the new script.
- **No off-the-shelf Upstox MCP connector exists** (I searched the registry — zero results). Your in-repo integration is the right and only path.

**What *would* need your device, later, and only for production scale:**
- A **multi-user / always-on deploy** can't share your personal token — each user does their own Upstox OAuth, or you license a **paid market-data vendor** (also a redistribution-licensing question that matters for monetization).
- **True streaming** (sub-second ticks) uses the **Upstox WebSocket V3** feed; wiring it is a build task, not a blocker — REST polling already gives minute-grade real-time.
- **Groww / Kite** (for real holdings): Groww token expired today; Kite unauthenticated → interactive login on your machine.

---

## 4. Proposed new simulation — "Anvil Live" (real-time index & stock prediction + monetization)

**Design stance (non-negotiable, and it's also your competitive moat): outputs are calibrated probabilities, ranges, and regime reads — never point price targets or guaranteed returns. Analytics & education, not investment advice. Read-only; abstention is a first-class output.**

### Data flow
```
Upstox  ──REST snapshots (chain+Greeks+OI)  ┐
        └─WebSocket V3 ticks (LTP, phase 2) ─┤
                                             ▼
            Ingest / normalize  (tick buffer, IST trading-clock gating, provenance tags)
                                             ▼
            Feature engine  (REUSE anvil/engine: Greeks, GEX, OI walls, IV term-structure,
                             realized-vol forecast, regime score, touch-probability)
                                             ▼
            ┌────────────── Prediction layer ──────────────┐
            │ INDEX:  P(touch K by T), expected-move band,  │
            │         VRP richness, regime-gated *abstaining*│
            │         direction lean, intraday range cone   │
            │ STOCK:  cross-sectional relative ranking       │
            │         (long/short), per-stock touch + vol,   │
            │         earnings/event IV-crush gating         │
            └───────────────────────────────────────────────┘
                                             ▼
            Calibration & ledger  (REUSE anvil/ledger + calibration: log every forecast with
                                   resolve_ts → score vs realized → LIVE reliability curve)
                                             ▼
            Monetization analysis layer  (NEW — see below)
                                             ▼
            Outputs: PWA dashboard (reuse web/), API, alerts, exportable PDF/Excel reports
```

### Prediction approach — and an honest account of the limits
- **Daily index *direction* is the wrong lead target.** Out-of-sample directional accuracy tops out around **53–57%**; anything advertising 60–80%+ is almost always leakage or overfit. So the index engine **leads with what's actually resolvable and useful to a buyer**: probability-of-touch, the implied expected-move band, variance-risk-premium richness, and a regime traffic-light. Direction, if shown at all, is a regime-conditioned **lean that is allowed to abstain**.
- **Stock prediction: predict *relative*, not *absolute*.** Forecasting a single stock's exact price is low-signal. **Cross-sectional ranking** (which names are likely to out/under-perform) is far more achievable and is the standard finding in the ML-asset-pricing literature. Per-stock touch-probability and volatility forecasts, gated around earnings, round it out.
- **ML comes last, as a referee — not an oracle.** Once a live track record accrues, a LightGBM **meta-layer** decides *act vs abstain* (meta-labeling) over the structural signals, with isotonic/Platt calibration and conformal bands — gated by the same anti-overfit battery (deflated Sharpe / PBO / t≥3) your repo already enforces. It never emits a naked "BUY" direction.
- Everything carries **data provenance** (live / backtest / demo / derived) and feeds a **public reliability curve**, so the over-confidence shown in §2 becomes visible and correctable instead of hidden.

### Monetization analysis layer (the new ask) — framed honestly
This layer **measures and models** monetization; it doesn't turn the product into a tipping service.
- **Tiering / value attribution:** which signals actually drive retention and conversion (free *calibrated daily brief* → premium = more underlyings, intraday cadence, alerts, history + export, API).
- **Unit economics:** data cost (your Upstox token now; a licensed vendor at scale), infra, per-user margin — so "maximum monetization" is grounded in real numbers, not a hand-wave.
- **Funnel + metering analytics:** usage events, entitlement gates, cohort/conversion dashboards.
- **Two real constraints I have to flag (not legal advice):**
  1. In India, **selling investment "tips/advice" can trigger SEBI Research-Analyst / Investment-Adviser registration**. An *analytics, education, and tools* product with clear disclaimers is a materially safer posture than "buy this, you'll make X." Worth a quick check with a professional before charging.
  2. **Redistributing broker/exchange market data** (e.g. showing live Upstox data to *paying third parties*) usually needs a **data-licensing agreement** — your personal token does not cover that. This shapes which monetization models are even viable.

### Build phases
- **Phase A — *no new credentials needed* (live feed already works):** streaming/poll ingest → real-time **index** forecaster → automatic live calibration logging. *(First component built today.)*
- **Phase B:** per-stock cross-sectional layer on equity chains/OHLC.
- **Phase C:** monetization analysis layer + entitlement scaffolding + unit-economics model.
- **Phase D:** ML meta-layer, gated by the anti-overfit battery.

---

## 5. What I built and ran today

`realtime_sim/live_index_forecast.py` — the **first working component** of Anvil Live, deliberately separate from the existing `anvil/live` engine. It's **read-only**, pure-stdlib (no installs), and proves the whole path **live chain → features → probabilistic forecast → JSON**. Run against your live feed just now it produced, for example:

- **NIFTY 24,150.9** — expected move ±132.7, 1-sigma band **23,955–24,347**, P(touch 24,300 up) **0.37** vs P(touch 24,100 down) **0.76**, PCR 1.08, call-wall 24,200 / put-wall 24,100.
- Plus BANKNIFTY and SENSEX, saved to a timestamped `snapshot_*.json`.

It already reuses your conventions (VRP discount = 0.85, reflection-principle touch, 0.85×straddle expected move) so it drops straight into the calibration ledger when you greenlight Phase A.

---

## 6. Security flag (please action regardless of direction)

Your real **`UPSTOX_API_KEY` and `UPSTOX_API_SECRET` are pasted into `.env.example`**, and `.env.example` **is tracked by git** (`.gitignore` explicitly un-ignores it). Your `.env` (with the live tokens + `ANVIL_SECRET_KEY` + Groww creds) is correctly gitignored — good — but the example file leaks the app credentials. Recommend: scrub `.env.example` back to placeholders, and **rotate the Upstox API secret** (and Groww creds, which were also in the working tree) since they've been committed.

---

## Decisions I need from you before the heavy build

1. **Monetization is a U-turn from your own roadmap.** `future_waves_of_upgrade.md` says *"Monetization — OUT (owner: flat-free, all features free). Do not raise."* You're now asking for **maximum monetization**. I'll follow the new direction — just confirm it's intentional, and whether the honest *analytics/education* framing + SEBI-safe posture is acceptable (vs. a more aggressive "signals" product, which I'd advise against on both ethics and regulation).
2. **What should "performance" track** — forecast calibration (a), paper P&L (b), or real holdings (c)?
3. **Scope of the first real build** — index-only real-time (ships fastest, zero blockers) first, or index + per-stock together?
