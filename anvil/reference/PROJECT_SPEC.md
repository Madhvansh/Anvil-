# Options Intelligence Platform — Build Brief

A calibrated options-intelligence platform for Indian markets (NSE/BSE), built with Claude Code. This document is the founding spec: vision, architecture, tech stack, roadmap, and the working method for building it with Claude Code. Drop it into your repo root and point Claude Code at it.

---

## 1. Positioning & thesis

The Indian retail options market is saturated with tipsters claiming "90% accuracy." That market is full of burned users and zero trust. **The wedge is to be the rigorous, transparent one.**

Core principle — we do not *claim* accuracy, we *prove* calibration:

- Every forecast is a probability, not a point target.
- Every probability ships with a live, auditable calibration score (Brier score + reliability diagram).
- The track record is public and updates in real time.

> "We don't promise accuracy. Here's our reliability curve." — a headline a tipster cannot copy, because they would fail it.

This is the brand moat: trust, earned through transparency, in a market that has lost it. It is also good product design and good user protection — probabilistic framing plus visible calibration plus clear disclaimers protects the people who act on the output.

---

## 2. Forecasting philosophy (read this before building the forecast engine)

This section is a hard design constraint, not a suggestion. Bake it into the models, the API contracts, and the UI.

- **Outputs are distributions and probabilities.** Expected-move cones, probability-of-touch, probability of closing within ranges, directional odds. Never a single "Nifty will be at X" with an implied certainty.
- **Calibration is a first-class, displayed metric.** Brier score, log loss, and reliability diagrams are computed continuously on realized outcomes and surfaced in the UI. A forecast without a calibration context is incomplete.
- **Honesty about what is knowable.** Expected-move ranges, vol regimes, relative value, and event-vol behavior are genuinely forecastable to useful precision. Precise directional point prediction is not — the models reflect that by widening uncertainty rather than faking confidence.
- **Disclaimers are product features.** Clear "this is probabilistic, not advice" framing, on every forecast surface.

The forecast engine can be as sophisticated as you like (ensembles, gradient boosting, sequence models). The constraint is purely on *how confidence is represented and reported* — truthfully.

---

## 3. Feature pillars

### Pillar 1 — Calibrated forecast engine
- Ensemble of three model families:
  - **Implied** — expected move from ATM straddle, IV term structure, skew.
  - **Statistical** — realized-vol models (GARCH family via `arch`), vol regime classification, mean-reversion of IV rank.
  - **ML** — gradient-boosted models (LightGBM/XGBoost) and optionally sequence models on engineered features.
- Feature set: IV term structure & skew, OI and participant flow, India VIX, realized-vs-implied vol spread, global cues (GIFT Nifty, US indices, crude, USDINR, US 10Y), technical context.
- Outputs: probability bands, probability-of-touch, directional probability, expected-move cone — each with model attribution.
- **Calibration service** (the differentiator): continuously scores forecasts against outcomes; serves Brier score, reliability diagrams, and band-coverage stats per horizon and per regime.

### Pillar 2 — Cross-broker unified risk book
- Consolidates positions across **Kite + Groww** (extensible to others).
- Net Greeks (delta, gamma, theta, vega) and **beta-weighted delta** to Nifty for true index exposure.
- Scenario grid (spot × IV) and **Monte Carlo P&L distribution** over thousands of vol/price paths; tail risk and probability-of-ruin.
- Margin/capital efficiency across brokers (SPAN + exposure, margin-to-premium, return-on-margin).
- Greeks computed locally (see Data layer) — not pulled from broker APIs.

### Pillar 3 — Event & regime intelligence
- Event calendar: Union Budget, RBI policy, earnings, expiry, F&O ban list, major macro prints.
- **IV-crush guard**: models expected post-event IV collapse and warns against long-premium entries into it.
- Vol regime classifier (calm / trending / stressed / event) driving regime-conditional forecasts.
- Term-structure signals (contango/backwardation, near-vs-far IV).

### Pillar 4 — Flow & positioning intelligence
- NSE participant-wise OI (FII / DII / Pro / Client) decoded into plain-language positioning narratives.
- FII index-futures long-short ratio tracking.
- **Unusual options activity scanner**: large OI deltas, IV spikes, abnormal volume.
- OI buildup classification (long buildup / short buildup / long unwinding / short covering) from price+OI jointly.

### Pillar 5 — Claude-native analyst copilot
- Natural-language interrogation of the live book, the chain, and the models — grounded in real data via tool use.
- Example queries: "What's my gamma risk if VIX spikes 4 points into Thursday expiry?" / "Show me every historical day where skew and FII OI looked like today, and the forward 5-day distribution."
- Generates research notes, scenario explanations, and trade rationales with sources.
- Built on the Claude API with tool-use over internal service endpoints + the broker MCP connectors.

### Pillar 6 — Honest backtesting & strategy lab
- Walk-forward and out-of-sample by construction; regime-conditional performance breakdown.
- Transaction costs, slippage, and liquidity/impact modeling.
- Look-ahead and survivorship-bias guards implemented as tests that fail the build if violated.
- Strategy templates + a clean interface to encode custom hypotheses.
- Experiment tracking (MLflow) so every backtest is reproducible.

### Pillar 7 — Behavioral trade journal
- Logs decisions and outcomes; computes behavioral leak metrics (loss aversion, IV-timing errors, holding winners/losers too long).
- Closes the loop: your personal edge/leak analytics over time.

---

## 4. Data layer

| Need | Source | Notes |
|---|---|---|
| Live positions, holdings, quotes | Kite + Groww **MCP connectors** | Real-time, per-user |
| Historical chain, OI, instruments | **Kite Connect API** | EOD OI available; intraday OI history is limited |
| Participant-wise OI, India VIX, chain ground-truth | **NSE** (`nsepython` / `jugaad-data` or direct) | Free; the participant data is under-used and valuable |
| Global cues | GIFT Nifty, US indices, crude, USDINR, US 10Y | For the forecast feature set |
| **Greeks** | **Computed locally** | Kite Connect does **not** expose Greeks via API |

**Greeks computation:** use **Black-76** (not Black-Scholes) via `py_vollib`, because Indian index options are priced/settled off futures. Add sanity tests that validate computed Greeks against broker-displayed values for a few known strikes.

**Storage:**
- Time-series + relational: **Postgres + TimescaleDB** for live/operational data.
- Backtest data lake: **DuckDB + Parquet** for fast, reproducible historical queries.
- **Redis** for caching live quotes/chains.

---

## 5. Architecture

Layered, service-oriented. Build a thin vertical slice first (ingest → Greeks → display), then widen.

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (Next.js + React)                                   │
│  dashboards · risk book · forecast + calibration · copilot UI │
└───────────────▲─────────────────────────────▲────────────────┘
                │ REST / WebSocket             │
┌───────────────┴─────────────────────────────┴────────────────┐
│  API layer (FastAPI)                                          │
│  auth · risk · forecast · flow · backtest · copilot endpoints │
└───┬──────────┬───────────┬───────────┬───────────┬───────────┘
    │          │           │           │           │
┌───▼───┐ ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐ ┌────▼──────────┐
│ Greeks│ │ Forecast│ │ Risk book│ │  Flow  │ │ Backtest lab  │
│ engine│ │ + calib │ │ + Monte  │ │ intel  │ │ (walk-forward)│
│(Bl-76)│ │ ensemble│ │  Carlo   │ │        │ │               │
└───┬───┘ └────┬────┘ └────┬─────┘ └───┬────┘ └────┬──────────┘
    │          │           │           │           │
┌───▼──────────▼───────────▼───────────▼───────────▼───────────┐
│  Data layer                                                   │
│  Kite/Groww MCP · Kite Connect API · NSE · global cues        │
│  Postgres/Timescale · DuckDB+Parquet · Redis                  │
└──────────────────────────────────────────────────────────────┘

         Claude copilot — tool-use over the API layer + MCP
```

---

## 6. Tech stack

- **Backend / quant:** Python — `numpy`, `scipy`, `pandas`, `py_vollib` (Black-76), `arch` (GARCH), `scikit-learn`, `lightgbm`/`xgboost`, optional `pytorch`.
- **Calibration/experiments:** `scikit-learn` calibration tools, `mlflow`.
- **API:** FastAPI + WebSockets.
- **Frontend:** Next.js + React + Tailwind; charting via `lightweight-charts` (price/IV), Plotly or D3 (distributions, reliability diagrams).
- **Storage:** Postgres + TimescaleDB; DuckDB + Parquet; Redis.
- **LLM:** Anthropic SDK (Claude API) for the copilot, tool-use over internal endpoints + broker MCP.
- **Infra:** Docker; deploy on a VPS/cloud; auth (Auth.js/Clerk); secrets via env/secret manager; structured logging.

---

## 7. Phased roadmap

Each phase ends with a concrete, demoable deliverable. Don't start a phase until the prior deliverable works.

- **Phase 0 — Foundation (Week 1).** Repo scaffold, `CLAUDE.md`, data ingestion (Kite + NSE), Greeks engine (Black-76), storage schema. *Deliverable: pull a live chain, compute Greeks, store it, query it.*
- **Phase 1 — Risk book (Weeks 2–3).** Cross-broker consolidation, net Greeks, beta-weighted delta, expected-move + IV-regime read. *Deliverable: see unified net Greeks + expected move across Kite + Groww.*
- **Phase 2 — Backtesting lab (Weeks 3–5).** Walk-forward engine, bias guards as tests, cost/slippage model, MLflow tracking. *Deliverable: test a hypothesis out-of-sample, reproducibly.*
- **Phase 3 — Forecast engine + calibration (Weeks 5–8).** Ensemble (implied + statistical + ML), probability outputs, **live calibration dashboard**. *Deliverable: calibrated probabilistic forecasts with a public reliability curve.*
- **Phase 4 — Flow & event intelligence (Weeks 8–11).** Participant-OI decoding, unusual-activity scanner, event calendar + IV-crush guard. *Deliverable: live positioning narratives and pre-event warnings.*
- **Phase 5 — Copilot + journal (Weeks 11–14).** Claude-native analyst over the API + MCP; behavioral trade journal. *Deliverable: converse with your live book; get leak analytics.*
- **Phase 6 — Hardening & beta.** Alerts, auth, deploy, onboard a handful of beta users.

---

## 8. Working with Claude Code (the method)

This is where finesse pays off. Treat Claude Code as a senior pair, not an autocomplete.

- **`CLAUDE.md` at the repo root** (template below) carries project context, conventions, architecture, and the forecasting-philosophy constraint so every session inherits it.
- **Thin vertical slice first.** Ingest → compute one Greek → display it end-to-end before building any pillar wide. Prove the pipe, then scale.
- **Test-driven for all quant code.** Greeks, risk math, and the backtester must be correct — write the tests first, have Claude implement to green. Validate Greeks against known/broker values.
- **Bias guards as failing tests.** Encode look-ahead and survivorship checks so a violation breaks the build. This is how you keep the backtester honest under pressure.
- **Plan before big modules.** Ask Claude Code to produce a written plan for each pillar before it writes code; review the plan, then build.
- **One service at a time, clean interfaces.** Keep modules decoupled so you (and Claude) can reason about them in isolation. Consider subagents for parallel workstreams (e.g., data ingestion vs. forecasting).
- **`/docs` for decisions.** Record design decisions and the *why*; future sessions read it.
- **Reproducibility.** Version data snapshots; every backtest must rerun to the same numbers.

### Starter `CLAUDE.md`

```markdown
# Options Intelligence Platform

## What this is
A calibrated options-intelligence platform for Indian markets (NSE/BSE).
Live data via Kite + Groww MCP connectors; historical/chain via Kite Connect API + NSE.

## Non-negotiable principles
- Forecasts are PROBABILITIES, never point targets with implied certainty.
- Calibration (Brier score, reliability diagrams) is computed continuously and
  displayed alongside every forecast. A forecast without calibration context is incomplete.
- No "high accuracy" / guaranteed-return claims anywhere in code, copy, or UI.
- Disclaimers (probabilistic, not advice) appear on every forecast surface.

## Technical facts
- Greeks are NOT available from Kite Connect's API — compute locally with
  Black-76 via py_vollib (Indian options settle off futures).
- Validate computed Greeks against broker-displayed values in tests.
- Backtester must be walk-forward / out-of-sample; look-ahead and survivorship
  guards are implemented as tests that fail the build if violated.

## Conventions
- Backend: Python (FastAPI). Frontend: Next.js + React + Tailwind.
- Quant code is test-first. No quant module merges without passing correctness tests.
- Storage: Postgres/Timescale (live), DuckDB+Parquet (backtests), Redis (cache).

## Build order
Thin vertical slice (ingest -> one Greek -> display) before widening any pillar.
Follow the phased roadmap in PROJECT_SPEC.md.
```

---

## 9. A note on accuracy claims and user protection

This is product strategy, not a legal lecture. Even setting regulators aside, asserting "high accuracy" on directional options forecasts means claiming something the instrument can't deliver, and the people who act on it lose real money. Building calibration transparency, probabilistic framing, and clear disclaimers is simultaneously: (a) the honest thing, (b) the thing that protects your users, and (c) your single strongest differentiator against the tipster crowd. The brand that survives in this space is the one that's trusted — and trust here is built by *showing your reliability curve*, not by claiming a number.
