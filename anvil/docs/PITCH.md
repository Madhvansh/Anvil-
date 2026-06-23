# Anvil — Investor Brief & Demo Script

> Analytics & education product for Indian index-options traders. Outputs are probabilities,
> ranges and regime reads with an auditable calibration record — never point targets, accuracy
> guarantees, or investment advice.

## 1. The problem

India's options-tips market runs on a claim that cannot be checked: *"90% accuracy."* Retail F&O
traders have no way to know whether anyone's calls are actually right, because no one publishes a
resolvable, time-stamped track record. Trust is asserted, never earned.

## 2. The product — we sell calibration, and we can prove it

Anvil forecasts NSE/BSE index-option outcomes as **probabilities** (e.g. *P(NIFTY closes within
this band by expiry) = 68%*) and publishes a **live reliability curve**: across everything we've
ever forecast, when we said 70%, did it happen ~70% of the time? That curve compresses to one
intuitive headline — the **Calibration Score** (`100 × (1 − calibration error)`). It is honest by
construction: it is computed only from **real, resolved forecasts**, and it shows "insufficient
data" rather than a flattering number until the sample is large enough.

That is the moat. A competitor can copy a feature in a week; they cannot copy a **track record that
only accrues over calendar time** — and we have already started the clock.

## 3. What is real today (runs end-to-end, test-gated)

- **Futures-correct quant engine.** Black-76 on the futures price, validated by put-call parity,
  finite differences, and a third-party library cross-check. Greeks, GEX + zero-gamma flip,
  market-implied (Breeden-Litzenberger) distribution, OI/PCR/max-pain, regime read, higher-order
  Greeks, and a beta-weighted cross-broker risk book.
- **A real, out-of-sample backtested calibration curve** built from free official **NSE/BSE EOD
  bhavcopy history** — with look-ahead and survivorship protection enforced as build-failing tests.
- **A live daily forecast loop** that logs forward forecasts and resolves them at expiry — the moat
  clock, running and idempotent.
- **The Calibration Score**, computed separately for the backtested and live curves, with synthetic
  data excluded from anything a user can see.
- **Live market data + your brokers**: Upstox (NSE+BSE chain/Greeks/IV), Groww (chain + positions +
  gated execution), Kite (positions → risk book). Real forward via futures settle or put-call parity.
- **A grounded AI copilot** that reasons only over engine numbers, behind a compliance guardrail,
  with a deterministic fallback. **Execution is gated/dry-run by default.**

## 4. What is honestly not done yet

Live forecasts have only just begun accruing, so the *live* Calibration Score is intentionally
"insufficient data" until the sample grows — the backtested curve carries the early proof. Broker
connectors light up once API keys are supplied. We label every synthetic and derived number; we do
not dress up a simulation as a track record. That discipline *is* the brand.

## 5. Demo script (≈5 minutes) — the app

1. **Open the app** (installable PWA, any device). Create the owner account, breeze through
   onboarding (index + detail level). Land on the **Daily Brief**: regime, market-implied expiry
   range, key OI walls, expiry risk, what changed, calibration status — five plain lines.
2. **Question-organized dashboard.** "Where can it move?" (range cone), "Pinned or unstable?"
   (regime traffic-light + zero-gamma flip), "Where are writers concentrated?" (OI walls), "Is
   premium expensive?" (IV/skew + IV-crush). Toggle **Simple → Trader → Expert** — same engine,
   more disclosure.
3. **The moat, made human.** The "How reliable has Anvil been?" card: the calibration diagonal +
   an honest score ("when we say 70%, it lands ~70%"), with synthetic data excluded by construction
   and an "insufficient data" gate until the live sample grows.
4. **Risk, intuitively.** Risk tab: beta-weighted book, a **scenario heatmap** ("if NIFTY ±X% and
   IV shifts…"), and a **Monte Carlo** P&L distribution (P(profit), VaR/CVaR) sampled from the
   market-implied distribution.
5. **Copilot + alerts.** Ask the grounded copilot "explain today simply" (and watch it refuse a
   buy/sell call). Add a `gex_flip_cross` alert and "Evaluate now" → a natural-language alert fires.
6. **Real data.** Connect Upstox → the provenance chip flips to **LIVE**; the daily cycle starts
   accruing the live track record. (Offline, the app shows last-known numbers with an "as of" label.)

## 6. Monetization

**Current build: every feature is unlocked — no tiers, no paywalls.** The focus now is trust, daily
habit, and accumulating the proprietary calibrated dataset. The data model carries a feature-flag
seam so packaging can be switched on later without rework.

The long-term model the moat supports (deferred — not built today): a subscription for
directional/buyer-leaning F&O traders, priced on the trust the curve earns — a free public
calibration tier as the credibility magnet, with live analytics, calibrated daily forecasts, the
cross-broker risk book, alerts, and the grounded copilot as paid depth. The reliability curve drives
both acquisition (proof nobody else has) and retention (it compounds over calendar time — the longer
a user stays, the deeper the record).

## 7. Roadmap

Deepen the live track record across all configured indices; expand the backtest horizon; add
event/regime conditioning (budget/RBI/expiry/IV-crush); broker-Greeks validation as a standing
gate; and, only as a separate and explicit decision, an execution tier (today gated off).
