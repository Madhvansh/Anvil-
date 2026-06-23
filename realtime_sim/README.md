# Anvil Live (`realtime_sim/`)

> ## ⭐ v2 — the maximum-monetization engine (start here)
>
> `python live_v2.py` is the **comprehensive** sim: live Upstox → VRP / GEX / regime read → ranked
> **option-structure** tips for **indices + stocks together**, gated/sized for the tail, with an
> honest scorecard (mandatory max-drawdown / CVaR / Sortino) and a **real, non-circular VRP backtest**
> (`backtest_v2.py`, India VIX vs realized). v2 exists because v1 below proved naive *direction* is a
> coin flip after costs — real money comes from harvesting the **variance risk premium** (selling rich
> option premium), not guessing up/down. Full write-up: `../Anvil_Realtime_Sim_v2_Report.md`.
>
> ```bash
> python live_v2.py                 # live read → ranked tip sheet → log → resolve → scorecard → VRP backtest
> python live_v2.py --backtest-only # just the real VRP edge prior (no network)
> ```
> v2 modules: `engine_v2` (VRP/GEX/regime/physical-RND) · `structures_v2` (the 7 option structures) ·
> `sizing_v2` (Kelly≤0.10 short-vol + caps) · `gate_rank_v2` (gate + portfolio stress cap + ranking) ·
> `costs_v2` (full India F&O stack) · `tracker_v2` (tips_v2.db + tail-aware scorecard) · `backtest_v2`.
> Honesty rails: measured-not-asserted, no gate circularity, conservative costs, no fake backtest,
> tail risk never hidden, read-only. Abstention is first-class. Not advice; SEBI line applies.

---

## v1 — the directional baseline (kept honest, kept losing)

A **real-time index + stock prediction simulation** built separately from the `anvil/live` engine
(synthetic / frozen-smile replay). v1 runs off the **live Upstox feed**, turns it into **honest,
calibrated directional tips**, and **tracks its own reliability over time**. It is retained as the
*baseline* v2 is measured against — naive direction is ~49% (a coin flip after costs), and v2 never
re-tunes it to look good.

> **Not investment advice. No guaranteed returns.** Outputs are probabilities and ranges for
> analytics & education. The package is **read-only**: it never places an order or moves money.
> "Maximising returns" here means *prediction quality + honest reliability*, not hype.

## The honest headline (read this first)

A v1 structural model (momentum + trend + mean-reversion + index option positioning) was
backtested walk-forward on ~440 sessions across 3 indices + 20 stocks (≈8,800 decisions):

- **Daily-direction hit-rate ≈ 49%** — at or below a coin flip, **negative after costs**.
- Longer horizons and cross-sectional momentum: also **no cost-aware edge** (see
  `research_horizons.py`).

This is the expected, literature-consistent result for simple signals on liquid large-caps, and
it is **why the app is built around calibration, not bravado.** Until measured edge appears, the
live model **recalibrates its confidence down to ~50% and defaults every tip to WATCH / abstain.**
The value today is the *measurement framework* + risk-framing analytics (expected-move bands,
probability-of-touch, IV/PCR context), not a directional oracle. Real edge must be **earned and
measured** before any tip becomes ACTIONABLE.

## What it does

1. **Live data** (`upstox_client.py`) — read-only Upstox REST: index option chains (IV/OI/Greeks),
   equity LTP, and daily/intraday candles. Resolves stock symbols via the public instrument master.
2. **Features** (`features.py`) — momentum/trend/RV/RSI from candles; ATM IV, expected move, PCR,
   OI walls, probability-of-touch from index chains. No look-ahead.
3. **Model** (`model.py`) — transparent, fixed-prior probability of an up move (no overfitting).
4. **Tips** (`tips.py`) — direction (UP/DOWN/NEUTRAL), **calibrated** confidence, entry, target,
   1-sigma band, horizon, rationale, full feature snapshot.
5. **Calibration** (`calibration.py`) — maps stated → measured confidence from the track record;
   gates tips ACTIONABLE only once edge is *verified*.
6. **Tracker** (`tracker.py`, the heart) — logs every tip, resolves it at its horizon, scores
   **calibration** (reliability curve, Brier, hit-rate by bucket) **and paper P&L** (entry/exit,
   win rate, expectancy, compounded return) into SQLite.
7. **Backtest** (`backtest.py`) + **research** (`research_horizons.py`) — honest, no-look-ahead
   evaluation and the candid reliability read above.

## Universe & horizons (configurable — see `config.py`)

- **Indices:** NIFTY, BANKNIFTY, SENSEX (full option chains).
- **Stocks (default 20 liquid Nifty-50/F&O names):** RELIANCE, HDFCBANK, ICICIBANK, INFY, TCS,
  SBIN, BHARTIARTL, ITC, LT, AXISBANK, KOTAKBANK, HINDUNILVR, BAJFINANCE, MARUTI, SUNPHARMA,
  M&M, WIPRO, ONGC, NTPC, TATASTEEL. Override with `ANVIL_RT_STOCKS="INFY,TCS,..."`.
- **Primary horizon:** `next_day` (next session close) — robust to resolve/backtest on free daily
  candles. `intraday` (today's close) also supported. Override with `ANVIL_RT_HORIZON`.

## Run it

```bash
cd realtime_sim
python live_index_forecast.py          # quick live index snapshot (bands, touch prob, PCR)
python run.py                          # generate + log tips for indices + stocks, print report
python run.py --horizon intraday       # today-close tips
python resolve.py                      # resolve due tips, print updated reliability (run daily)
python backtest.py                     # honest walk-forward reliability read
python research_horizons.py            # where (if anywhere) is there cost-aware signal?
python seed_history.py --fresh         # backfill DEMO: populate a sample reliability report now
```

The Upstox token is read from `../anvil/.env` (`UPSTOX_ACCESS_TOKEN`) or the environment. The
current cached token is an *extended* token valid into 2027, so no daily re-login is needed. A
browser User-Agent is sent because Upstox sits behind Cloudflare (it 403s the default agent).

To accrue a real **live** track record, schedule `resolve.py` daily after the cash close; tips
generated today resolve tomorrow and the reliability report fills in automatically.

## How the live feed plugs into the rest of Anvil

`tracker.py`'s forecast/outcome schema mirrors `anvil/ledger`, so these tips can feed the app's
existing calibration UI. The natural upgrades (all measured before trusting): richer features from
the existing `anvil/engine` (GEX, OI dynamics, IV term-structure, event/earnings gating), an Upstox
**WebSocket V3** streaming driver for sub-second ticks, and an ML meta-layer gated by Anvil's
anti-overfit battery (DSR/PBO). Until then: honest analytics, abstention-first.

## Notes

- **Storage:** SQLite DB defaults to `realtime_sim/tips.db`; relocate with `ANVIL_RT_DB` if your
  folder is on a network drive where SQLite locking misbehaves.
- **Compliance:** read-only; no execution. In India, paid investment *advice* can trigger SEBI
  Research-Analyst registration — this stays in the analytics/education lane with open reliability,
  not "buy this for guaranteed X". Keep it that way.
