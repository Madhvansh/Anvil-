# Anvil — India Options Intelligence Engine

Phase 1 foundation: data ingestion + an **in-house** analytics/Greeks engine + a proprietary
time-series store. Everything the rest of the product (proactive AI agent, prediction ledger,
risk cockpit) is built on.

> **Design rule:** the engine never depends on a broker for Greeks. The official Kite MCP is
> read-only and exposes OI but **no option chain / Greeks / IV** — we compute those ourselves
> from chain IV + spot + risk-free rate. Kite is used only to *read your positions*. Chain +
> OI + Greeks + IV come from Upstox/Dhan (or a paid vendor at scale).

## What's here

```
anvil/
  config.py            settings, feature flags (TRADING_AUTOMATION stays OFF), lot sizes
  models.py            normalized schemas: OptionType, Greeks, ChainRow, OptionChain, Position, Snapshot
  engine/
    greeks.py          Black-Scholes-Merton Greeks (δ/γ/θ/ν/ρ) + implied-vol solver
    higher_order.py    vanna, charm, vomma (dealer-flow Greeks)
    oi.py              OI buildup matrix, change-in-OI, PCR, max pain, OI walls
    gex.py             GEX (spot²-scaled, explicit dealer sign), zero-gamma flip, gamma walls
    implied_dist.py    Breeden-Litzenberger risk-neutral density + ATM-straddle expected move
    vol.py             IV rank/percentile, realized vol, skew, term structure
    portfolio.py       beta-weighted portfolio Greeks (normalized to NIFTY/BANKNIFTY)
    regime.py          GEX-informed regime read (mean-revert vs trend-amplify)
  ingest/
    base.py            Connector interface
    demo.py            offline synthetic chain + positions (runs with no API keys)
    upstox.py          chain + Greeks + IV + OI  [needs UPSTOX_ACCESS_TOKEN]
    dhan.py            REST chain fallback         [needs DHAN_* ]
    kite.py            positions / OI quotes (read-only)  [needs KITE_* or MCP]
    nse_eod.py         participant-wise OI, FII/DII, India VIX (EOD scrape)
    macro.py           risk-free rate, futures forward
  store/timeseries.py  DuckDB snapshot writer/reader (the moat dataset)
  api/app.py           FastAPI: /chain /greeks /gex /implied-dist /portfolio-risk /snapshot
  cli.py               `anvil pull NIFTY --demo`
tests/                 pytest suite (runs fully offline)
```

## Quickstart (offline, no keys)

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
pytest                            # engine tests, all offline
python -m anvil.cli pull NIFTY --demo
```

## Going live

Copy `.env.example` to `.env`, fill in **Upstox** (primary chain/Greeks/IV) and **Kite**
(positions, read-only). Then `python -m anvil.cli pull NIFTY` (drops `--demo`).

## Compliance posture (built in)

- `TRADING_AUTOMATION` feature flag defaults **OFF**; the order layer is a pluggable seam
  (`AssistedExecutor` now, `AutoExecutor` gated for later — requires SEBI algo empanelment).
- Engine outputs are **calibrated probabilities / ranges / regime reads**, not buy/sell calls.
- Not investment advice. See plan for full SEBI guardrails.
