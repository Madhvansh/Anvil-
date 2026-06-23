# Anvil Live — Build Report (real-time index + stock prediction simulation)

*Built 22 Jun 2026. Read-only market data only; no orders, no money movement. Not investment
advice; no guaranteed returns. "Maximising returns" = prediction quality + honestly-tracked
reliability, with the app staying free.*

---

## What I built

A new package, **`realtime_sim/` ("Anvil Live")**, separate from the existing `anvil/live`
engine (which runs on synthetic / frozen-smile replay). Anvil Live runs off the **live Upstox
feed** and does four things:

1. **Predicts** — generates tips for **3 indices (NIFTY, BANKNIFTY, SENSEX) + 20 liquid stocks**
   (configurable): direction, calibrated confidence, entry, target, 1-sigma band, horizon.
2. **Tracks itself (the heart)** — logs every tip and later resolves it against the realized
   price, scoring **calibration** (reliability curve, Brier, hit-rate by confidence bucket) **and
   paper P&L** (entry/exit, win rate, expectancy, compounded return) into SQLite.
3. **Recalibrates honestly** — maps stated confidence to *measured* reliability, so it never shows
   a number it can't stand behind; defaults to abstain when no edge is proven.
4. **Backtests candidly** — walk-forward, no look-ahead, and reports limitations plainly.

Modules: `config · upstox_client · features · model · calibration · tips · tracker · backtest ·
research_horizons · run · resolve · seed_history · live_index_forecast`. Pure Python stdlib (no
installs), so it runs anywhere the Upstox token is reachable.

## It works on live data (verified today, ~10:30–11:00 IST, market open)

- Live snapshot e.g. **NIFTY 24,157 · BANKNIFTY 57,876 · SENSEX 77,277**, full chains + Greeks.
- `run.py` generated and logged **23 tips** across indices + stocks; `seed_history.py` proved the
  resolve+scoring path on **345 backfilled tips** (real history, no look-ahead).

## The honest reliability read (this is the important part)

A v1 structural model (momentum + trend + mean-reversion + index option positioning) was
backtested walk-forward over ~440 sessions × 23 underlyings (**≈8,800 decisions**):

| Test | Result |
|---|---|
| Daily-direction hit-rate (all) | **49.2%** (indices 49.7%, stocks 49.2%) |
| Net expectancy after costs | **−0.089% / trade** (compounding negative) |
| Recent 30% hold-out | 49.0% — same story, not a one-regime fluke |
| Time-series momentum (5/10/20/60d × 1/5/10/20d holds) | negative net EV in **every** cell |
| Cross-sectional momentum (long top5 / short bottom5) | ≈ zero; best cells +0.1–0.8% ann (noise) |
| Reliability of raw confidence | says 55–65%, **delivers ~49%** → systematically overconfident |

**Plain conclusion:** simple price signals have **no exploitable daily edge** on liquid Indian
large-caps after costs. This is the expected, literature-consistent result (your own repo notes a
~53–57% OOS ceiling, and that's for sophisticated ML). It is **not** a disappointment — it's the
system doing exactly what you asked: measuring reliability honestly instead of selling a fantasy.

Because of this, the live model **recalibrates every raw 65% lean down to ~50%** and marks all
current tips **WATCH (unproven), 0 ACTIONABLE**, with a standing "edge NOT proven — default
abstain" banner. A backfilled sample run confirmed the machinery end-to-end: 319 resolved
directional tips, hit-rate ~53% in that recent window, **paper P&L still −4.9% after costs** —
i.e. even a slightly-better-than-coin window doesn't beat costs with this naive signal.

## How the tracking works (so you can trust it over time)

- **Log:** every generated tip is written with its features, confidence, target, band, horizon.
- **Resolve:** `resolve.py` (run daily after close) fetches the realized close at each tip's
  horizon — next-session close for `next_day` — with **no look-ahead**.
- **Score, two ways:**
  - *Calibration:* "when we say X%, does it happen X%?" → reliability curve + Brier + hit-rate.
  - *Paper P&L:* "what if you acted?" → enter at tip price, exit at horizon close, minus 8 bps
    round-trip cost → win rate, expectancy, compounded return, equity curve.
- **Gate:** a tip only becomes ACTIONABLE once a confidence bucket's *measured* hit-rate clears the
  bar on a real sample. Until then everything is WATCH/abstain. Abstention is first-class.

This is the honest path to actual returns: trust is earned by a visible, resolving track record —
not by confident-sounding predictions.

## What's genuinely useful right now (vs. what must wait)

- **Useful now:** the live index analytics — expected-move bands (~0.8–1.1% for this week's
  indices), probability-of-touch, IV/PCR/OI-wall context — which are about **sizing and risk
  framing**, and are directly calibratable. Plus the abstention discipline (don't trade noise).
- **Must be earned + measured before trusting:** any directional "buy/sell" tip. The framework is
  ready to measure richer signals — `anvil/engine` features (GEX, OI dynamics, IV term-structure,
  earnings/event gating), an Upstox **WebSocket V3** streaming driver, and an ML meta-layer gated
  by your existing anti-overfit battery (DSR/PBO). Those are the credible routes to real edge.

## Security

The real Upstox API key/secret in the git-tracked `anvil/.env.example` were **scrubbed to
placeholders**. Your live secrets remain only in `anvil/.env` (gitignored). **You still must
rotate the Upstox API secret on Upstox's side** (and Groww creds), since they were committed.
(A `anvil/.env.example.bak` was created during the scrub and emptied — it has no secret; delete
it at your convenience.)

## Run it

```bash
cd realtime_sim
python live_index_forecast.py     # live index bands / touch-prob / PCR
python run.py                     # generate + log tips, print reliability report
python resolve.py                 # resolve due tips (schedule daily after close)
python backtest.py                # the honest reliability read above
python seed_history.py --fresh    # populate a sample reliability report immediately
```

See `realtime_sim/README.md` for full detail. Bottom line: the simulation is built, live, and —
above all — **honest about what it can and can't do.**
