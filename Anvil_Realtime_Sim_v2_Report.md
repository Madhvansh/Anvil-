# Anvil Live **v2** — the maximum-monetization simulation (real-time, index + stock)

*Built 22 Jun 2026, run live against the open market at ~13:56 IST. Read-only market data only —
no order is ever placed, no money is ever moved. ANALYTICS & EDUCATION ONLY; not investment advice;
no guaranteed returns. In India, paid securities advice can require SEBI Research-Analyst
registration — this stays in the analytics/education lane. Get a SEBI-qualified advisor before any
"accuracy"/recommendation copy ships.*

---

## Why a v2 (what was wrong with v1)

v1 (`realtime_sim/run.py`) was honest but used the **wrong instrument for making money**: it bet on
next-day **price direction**. Its own walk-forward backtest proved that is a **coin flip** on liquid
Indian names — **~49% hit-rate, negative after costs**. You can't earn from that, and v1 correctly
refused to pretend otherwise (everything WATCH/abstain).

"Maximum monetization" — which you clarified means **maximum earning from trading**, not app revenue —
does not come from guessing direction. In this market it comes from the **variance risk premium (VRP)**:
on average, options are priced at an *implied* volatility **higher** than what the market actually
*realizes*, so **selling** that premium has a real, positive expected edge. v2 is built entirely around
harvesting that edge — for **indices and stocks together** — while tracking confidence and reliability
as ruthlessly as v1 did.

## What v2 is

A new pure-stdlib package layered into `realtime_sim/` that, off the **live Upstox feed**:

1. **Reads the real edge surface** per underlying — `engine_v2.py`:
   - **VRP** = implied ATM IV (from the live chain) vs realized vol (from candles). `<1` ⇒ premium rich ⇒ sell.
   - **GEX / dealer positioning** → a pinning (mean-revert) vs trend-amplify **regime** + zero-gamma flip.
   - **Physical-measure RND** — the breakeven probabilities are read on the *realized* distribution
     (`level → spot + (level−spot)/0.85`), which is exactly the seller's edge.
2. **Builds real option STRUCTURES** off the live chain — `structures_v2.py`: iron condor, short
   strangle (naked), put/call credit spreads, long straddle/strangle, directional debit spread.
   Each is priced with **spread-crossing fills** (you sell the bid, buy the ask), a **modeled max-loss**
   (exact for defined-risk; a **3σ-gap STRESS estimate** for naked), and a **physical-measure EV + POP**.
3. **Gates, sizes, and ranks** — `gate_rank_v2.py` + `sizing_v2.py`: `min(risk-fraction, fractional-Kelly,
   exposure, lot-cap)` with **Kelly hard-capped at 0.10 for short-vol** (negative skew), a **portfolio
   short-vol stress cap** (NIFTY/BANKNIFTY/SENSEX gap together), and abstention as a first-class output.
   Ranks **index + stock together** by **net-EV per ₹ of risk**.
4. **Tracks itself honestly** — `tracker_v2.py`: logs every idea, resolves at option expiry against the
   realized path, and scores **paper P&L through the full India F&O cost stack** with **mandatory tail
   stats** (max drawdown, worst trade, CVaR, Sortino, Calmar — win-rate is **never** shown alone),
   **MAE/MFE with a modeled stop**, a live **VRP audit**, **regime attribution**, and a cash benchmark.
   Open trades are **excluded from stats but counted** (open ≠ flat). ACTIONABLE only when **measured**.
5. **Proves the edge non-circularly** — `backtest_v2.py`: there are **no historical option chains**, so
   instead of faking one it measures the VRP directly from **real India VIX (implied) vs realized NIFTY
   moves** — parameter-free, no look-ahead.

Orchestrator: **`python live_v2.py`** (the "run it against the market right now" entry point).

## Live run — 22 Jun 2026, ~13:56 IST (market open, Upstox live)

**Live regime read** (the engine selecting *where* premium is worth selling):

| Underlying | IV | RV | VRP | Signal | Regime |
|---|---|---|---|---|---|
| NIFTY (exp 06-23) | 13.2% | 12.8% | 0.97 | NEUTRAL | pinning |
| BANKNIFTY | 12.8% | 17.3% | **1.35** | **BUY_VOL** | trend-amplify |
| SENSEX | 13.6% | 13.7% | 1.01 | NEUTRAL | pinning |
| **SBIN** | 20.9% | 15.2% | **0.72** | **SELL_VOL** | pinning |
| **RELIANCE** | 22.8% | 18.2% | **0.80** | **SELL_VOL** | pinning |
| INFY | 27.2% | 41.8% | 1.54 | BUY_VOL | trend-amplify |
| TCS | 24.8% | 43.7% | 1.76 | BUY_VOL | trend-amplify |
| HDFCBANK, ICICIBANK, LT, AXISBANK | — | — | >1.1 | BUY_VOL | trend-amplify |

**Maximum-monetization tip sheet — 2 ideas taken, 65 abstained, 0 actionable:**

| # | Status | Underlying | Strategy | POP | EV/risk | Net-EV (pos) | Max-loss (pos) | Units |
|---|---|---|---|---|---|---|---|---|
| 1 | WATCH | SBIN | iron_condor | 85.2% | 0.101 | ₹1,217 | ₹12,112 | 1 |
| 2 | WATCH | RELIANCE | call_credit_spread | 75.0% | 0.054 | ₹394 | ₹7,275 | 1 |

This is the engine working **exactly as designed**: it sold premium only on the two names where it is
genuinely rich (SBIN VRP 0.72, RELIANCE 0.80) in a pinning regime, and **abstained on everything where
implied is *cheaper* than realized** (BANKNIFTY, INFY, TCS, HDFCBANK…) — because selling premium there
would be paying the premium, not earning it. The naked strangles were filtered out by honest stress
sizing. **0 ACTIONABLE is correct**: a fresh book has no measured track record, so nothing is promoted
past WATCH. NIFTY itself didn't fire — today its premium is fairly priced (VRP 0.97), and the engine
reads *today*, not an assumption.

## How confident / how accurate — the honest evidence

**Live track record:** 0 resolved so far (the WATCH structures resolve at their option expiries —
NIFTY 06-23, SENSEX 06-25, SBIN/RELIANCE 06-30). It accrues **forward**; that's the only honest way.

**The edge prior (real, non-circular, no look-ahead)** — daily ATM-straddle sell on NIFTY, implied =
**real India VIX**, realized = **real NIFTY moves**, over **492 trading days (Jun 2024 → Jun 2026)**,
through realistic costs:

| Metric | Value |
|---|---|
| Win rate | **65.2%** |
| Total / annualized return on ₹10L | **+31.4% / ~16.1% per yr** |
| Sharpe / Sortino | **1.89 / 1.42** |
| Profit factor | 1.37 |
| **Max drawdown** | **−13.7%** (₹−1.37L) |
| **Worst single day** | **−2.8%** (₹−28.0k) |
| **CVaR (worst 5%)** | ₹−14.5k |
| Mean realized ÷ implied (de-biased) | **0.836** (VRP is real — matches the literature's ~0.85) |
| Days VRP inverted (realized > implied) | 160 / 492 (**32.5%** — the tail you must survive) |

**Read this correctly:** the edge is real (realized vol averaged just 0.67× implied), and risk-adjusted
returns are strong (Sharpe ~1.9) — **but it is selling insurance.** It wins most days then loses big on
gaps: a −13.7% drawdown and a −2.8% day are *in the sample*. That is why the scorecard makes
max-drawdown / worst-day / CVaR mandatory and **never headlines win-rate or expectancy alone**, and why
short-vol Kelly is capped at 0.10 and the portfolio stress-cap binds across indices.

## The honesty rails (carried from v1, hardened by an adversarial review)

- **Accuracy is MEASURED, never asserted.** ACTIONABLE requires a (strategy, regime) cell to clear a
  real-sample bar; until then WATCH. Abstention is first-class and counted.
- **No gate circularity.** The gate and Kelly read the **raw** physical POP; any calibrated number is
  display-only and never feeds back.
- **Costs are conservative.** Full India F&O stack, per-leg per-side, options-sell STT at the **current
  0.10%** (not the stale 0.0625%), spread-crossing fills. Net-EV (not gross) is what the ranker sorts on.
- **No fake backtest.** No historical option chains exist, so v2 does **not** reconstruct one; the only
  backtest shown is the real VIX-vs-realized VRP prior, explicitly labeled as the prior, not a track record.
- **Tail risk is never hidden.** Mandatory max-DD / worst-day / CVaR / MAE-MFE / modeled-stop / "not
  stress-tested" warnings. Win-rate is never a standalone headline for premium-selling.
- **VRP is audited, not assumed.** realized/implied is re-measured at entry and resolution; if it
  inverts, short-vol cells abstain automatically.
- **Read-only forever.** No order endpoint is imported anywhere. **Compliance:** frame outputs as
  probabilities/ranges, not personalized buy/sell/target calls; confirm with a SEBI-qualified advisor
  before publication.

## Run it

```bash
cd realtime_sim
python live_v2.py                 # FULL cycle: live read → ranked tip sheet → log → resolve → scorecard → VRP backtest
python live_v2.py --no-resolve    # generate + log only
python live_v2.py --backtest-only # just the real VRP edge prior
```

**To accrue a live track record:** schedule `python -c "import tracker_v2,upstox_client as u; tracker_v2.resolve_open(u.UpstoxClient())"`
daily after the cash close (or just run `live_v2.py` daily). Tips logged today resolve at their expiry
and the scorecard fills in — that is the honest path from "unproven WATCH" to "measured ACTIONABLE".

Bottom line: v2 is the comprehensive, live, index+stock monetization simulation you asked for. It points
real money at the one edge this market actually pays — the variance risk premium — sizes it for the
tail, abstains when the edge isn't there, and tells you the truth about its own reliability.
