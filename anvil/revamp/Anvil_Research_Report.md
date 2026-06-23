# From 55% to a Real Edge
### A brutally-honest research report for Anvil — short-horizon Indian index options (NIFTY / BANKNIFTY / SENSEX) and stocks

*Prepared for: Madhvansh · Horizon: intraday and 1–5 days · Scope: extend the existing Anvil engine · Posture: paper & analytics only*

---

## 0. The one-page verdict

You asked for two things: push accuracy from ~55% to 70%+, and don't tell you it can't be done. Here is the honest version of both, because the honest version is also the one that makes money.

**1. You already have ">70% accuracy." It is worthless, and your own evidence pack proves it.** Your NIFTY short-strangle cells hit **86.8%** and **93.9%** win-rate *out-of-sample*. That *is* "70%+ accuracy." You don't ship it because those are negative-skew short-volatility structures — win small ~90% of the time, lose big ~10% — with Deflated Sharpe **0.00**. So "raise the accuracy number" is already solved and already a trap. Accuracy and profit are different axes; optimizing the first pushes you straight into bets that blow up.

**2. Unconditional 70% directional accuracy on a liquid index is not real.** Across the rigorous, leakage-controlled, cost-aware literature, the honest out-of-sample ceiling for liquid-index direction at intraday-to-5-day horizons is **low-to-mid 50s percent** — roughly 52–55%, and ~50–53% after costs. The state-of-the-art "serious ML" result (Gu–Kelly–Xiu, *RFS* 2020) is a **sub-1%-per-month R²** harvested across *thousands* of stocks, not a high hit-rate on one index. Every public "85%/99% NIFTY accuracy" paper I examined is one of four artifacts: predicting price *levels* (so "tomorrow ≈ today" scores 99%), data leakage, undisclosed trial counts, or single-path walk-forward. Your realized **55.9%** is already at or slightly *above* what credible studies achieve. Your stated **68.7%** is textbook over-confidence.

**3. But your real goal — a system that is reliably right enough to make money — is absolutely achievable, and there is large room to improve.** The improvement does not come from a bigger accuracy headline. It comes from three moves that the evidence strongly supports: **(a) selective prediction** — trade only the high-confidence subset and report *accuracy-at-coverage*, which can *legitimately* sit at 65–75%+ on, say, the top 20–30% of days; **(b) calibration + a bet/no-bet meta-layer** so "70%" actually means 70%; and **(c) harvesting the one edge in Indian options that is peer-reviewed and real — the variance risk premium — instead of guessing direction from PCR and max-pain folklore.** Net: the same engine, re-pointed from "be right more often" to "be right *when it bets*, and bet only with positive post-cost expectancy."

**So the target changes from a lie you'd have to defend in diligence to a number you can prove:** not "70% accuracy," but **"X% precision on the Y% of signals we actually take, with positive post-cost edge and a t-stat over 3."** That is a harder, smaller, real thing — and it is genuinely innovative, because almost nobody in the Indian retail-tips space sells it.

The rest of this report is the evidence, the ranked methods, and exactly what to build. The companion document is the Claude Code build plan.

---

## 1. Why "55% → 70% accuracy" is the wrong objective (read this twice)

Three facts, each independently fatal to the accuracy-headline framing:

**Accuracy ≠ edge.** A short strangle wins ~90% of the time and still loses money over a full cycle because the 10% of losses are huge. A trend trade wins ~40% of the time and makes money because the wins are large. Your pack already shows this: the 87–94% win-rate cells all carry Deflated Sharpe 0.00 and stay "not verified." If you optimize the engine toward a higher hit-rate, the optimizer will *rationally* walk it into more short-vol — i.e., toward the steamroller. **The accuracy knob and the survival knob turn in opposite directions.**

**The ceiling is real and low.** A weak-form-efficiency study spanning 100 S&P-500 names + 4 indices (2008–2018, recursive walk-forward) found prediction accuracy "approximately normally distributed about a mean of **52%**," best model ~55.6%, alpha centered on zero [arXiv 1909.05151]. On CSI-300 *index futures*, technical rules were significant gross but "trading profits will be eliminated completely" after costs [arXiv 1710.07470]. There is no credible evidence anywhere of a durable 70%+ all-conditions hit-rate on a liquid index.

**Where the fake 70–99% numbers come from.** (i) *Level prediction*: a model with MAPE 0.0137% is just saying "tomorrow's price ≈ today's" — it scores ~99% on price error and ~50% on *direction*. (ii) *Leakage*: a field-wide reproducibility problem — Kapoor & Narayanan catalog leakage across 329 papers; proper subject-wise splits routinely drop "95–99%" to 66–90% [Patterns, S2666389923001599]. (iii) *Selection*: Bailey–Borwein–López de Prado–Zhu show that with 5 years of data, testing as few as **~45 configurations guarantees** a strategy with great in-sample and "dismal" out-of-sample performance [Notices of the AMS, 2014]. (iv) *Single-path walk-forward* is still one history and overfits easily. **Your 55.9% realized vs 68.7% stated is exactly this gap, and it will not close by trying harder on accuracy.**

> The deliverable you actually want is not a number that's high; it's a number that's **honest and bankable**. That is your moat. Re-read your own investor takeaway: *"a rigorous anti-overfitting gate, a live public reliability curve, and abstention when there is no edge survives diligence; a '70–800% accuracy' claim does not."* You were right. This report tells you how to make that honest engine genuinely *better*, not how to abandon it.

---

## 2. The honest ceiling — and the one legitimate way past it

You cannot move *unconditional* accuracy much past the mid-50s. You **can** move two things that matter far more:

**(A) Post-cost expectancy** — from ~0 (where your gate currently, correctly, says "not verified") to positive, by harvesting real premia and cutting the trades that only ever paid in-sample.

**(B) Conditional accuracy at a chosen coverage** — this is the legitimate "70%." The mechanism is *selective prediction*: a classifier that is allowed to abstain trades only its high-confidence subset, moving up the risk–coverage curve. "Trading via Selective Classification" demonstrates exactly this on intraday futures — abstain when not confident, and accuracy on taken trades rises along an explicit accuracy–coverage trade-off [arXiv 2110.14914]. The catch that keeps it honest: you must **always report the coverage**. "72% right on the 22% of days we traded" is real and sellable. "72% right" with the denominator hidden is the same lie as before.

There is also a documented *conditional* directional edge worth naming because it is the template: **market intraday momentum** — the first half-hour return predicts the last half-hour return, statistically and economically, concentrated on high-volatility / high-volume / macro-news days [Gao, Han, Li & Zhou, *JFE* 2018]. That is what a real edge looks like: narrow, regime-specific, time-of-day-specific — not an all-day 69%.

**Realistic, provable targets for Anvil** (to be *certified by your gate*, never assumed):
- Turn the post-cost edge on the *traded* book from ≈0 to **positive with t > 3** on multi-year data.
- Conditional accuracy on the top-confidence decile/quartile of **~62–72%**, at **coverage of 15–35%** of days, *with* that coverage disclosed.
- Brier score from **0.251** (coin-flip) toward **~0.18–0.21**, and a reliability curve that actually tracks the diagonal.

Those are honest, defensible, and a genuine leap from where you are. They will not read as "70% accuracy" on a billboard. That is the point.

---

## 3. Where real edge lives — method families, ranked by evidence

I ran five independent research tracks and competed the studies against each other. Here is the ranking by *strength of evidence for genuine, post-cost, out-of-sample edge at your horizons*. This is deliberately not ML-first — your instinct that "ML alone may not be the answer" is correct and the evidence backs it.

### Tier S — Build these first (highest ROI, lowest risk of self-deception)

**S1. Selective prediction + meta-labeling (the bet/no-bet brain).**
A secondary model decides whether to act on the primary signal. López de Prado's meta-labeling raises precision on taken trades; honest out-of-sample replications show **modest but real gains** (precision +3–6 points), *not* the rosy in-sample numbers [Hudson & Thames replication]. Critical nuance the research surfaced: meta-labeling helps most when the primary is rules-based/quant *or* the meta-model is fed **orthogonal** features (regime, volatility state, microstructure); it can *hurt* an already-tuned ML primary. Anvil's primary is rule-based quant (Black-76, momentum, HAR-RV) — **this is the ideal setup for meta-labeling.** Pair it with conformal selective prediction (below) to get coverage control.

**S2. Conformal / calibrated selective prediction (the honesty layer).**
Conformal prediction gives distribution-free coverage guarantees and lets you report accuracy-at-coverage directly. The load-bearing caveat: the vanilla guarantee assumes exchangeability, which financial series violate — so use a **time-series-adaptive** variant (ACI / sequential SPCI / temporal conformal) and recalibrate on a cadence [arXiv 2212.03463; 2507.05470]. Combined with isotonic/Platt calibration, this is what makes "when it says 70%, it's 70%" true on the live reliability curve — your stated differentiator.

**S3. Validation rigor you already started — finish it.**
Your CPCV + Deflated Sharpe + PBO + Harvey t≥3 gate is correct and rare. A controlled study confirms **CPCV gives the lowest probability of backtest overfitting** among common schemes [Expert Systems w/ Applications, S0950705124011110]. The only thing wrong with your gate is that it has too little data to certify anything — which is a *data* problem, not a *method* problem (see §6). This is the cheapest win you have: **more history, same gate.**

### Tier A — Build these second (real edge, but narrower than the folklore claims)

**A1. Variance Risk Premium harvesting — the only peer-reviewed *real* edge in Indian options.**
Market-neutral straddles on NIFTY earn **negative, statistically and economically significant** returns — option buyers systematically overpay [Bajaj/Bansal et al., *IREF* 2020]. And it's **overnight-concentrated**: short-NIFTY-option returns are positive overnight, negative intraday [Bhat, *J. Futures Markets* 2024]. This is your genuine structural alpha — but understand what it is: a **volatility-selling, hold-overnight, tail-risky** edge, *not* a directional one. It must be vol-regime-scaled and tail-budgeted (it is the same engine as your 94% short-strangle cells, so it needs the steamroller managed, not ignored).

**A2. HAR-RV volatility forecasting (the sizing & regime workhorse).**
Corsi's HAR-RV beats GARCH out-of-sample for realized volatility [Corsi 2009; confirmed in recent horse-races]. It forecasts *volatility, not direction* — so its job is position sizing, option-pricing sanity, regime detection, and feeding the meta-layer. EOD-feasible today. High transfer, low risk.

**A3. Regime gating (HMM / Markov-switching / change-point).**
Only fire a signal where it has demonstrated edge (vol regime, trend vs mean-revert). This is how you convert a weak unconditional signal into a strong conditional one, and it pairs directly with selective prediction. BANKNIFTY ≈ 1.3–1.5× NIFTY volatility — **never pool them**; treat as separate regimes.

**A4. Gradient-boosted trees on engineered features (the ML workhorse — not deep nets).**
On noisy *tabular* financial features at your data scale, XGBoost/LightGBM beat deep nets [Grinsztajn et al., NeurIPS 2022, across 45 datasets]. This is your ML layer: feature engineering + GBM + the meta-labeling head above. Boring, fast, and state-of-the-art for this data shape.

### Tier B — Conditional / supporting (use as features, not headlines)

- **Short-horizon mean-reversion / reversal** — real negative autocorrelation in liquid names, but thin and cost-sensitive; must clear NSE's ~0.77% cash spread and wider option spreads. A small edge, EOD-feasible.
- **Market intraday momentum** (first-30-min → last-30-min) — a genuine *conditional* edge, but needs intraday data and is crowded/cost-sensitive.
- **News / event features (GDELT, results calendar)** — useful as *regime/context* features (especially event windows for VRP), not as standalone direction predictors.
- **Time-series momentum (TSMOM)** — real but at a **monthly** horizon (wrong for you), partly a vol-scaling artifact, Sharpe decayed ~40% post-2008. At best a slow overlay tilt.

### Tier C — Do not build as alpha (folklore or wrong-tool)

- **Deep sequence/forecasting nets (LSTM / TFT / N-BEATS / N-HiTS).** The M-competitions show deep learning routinely *fails to beat simple statistical baselines*; its published finance wins are largely leakage-inflated; the genuine improvements are single-digit-percent on *benign* data and won't survive Indian option spreads [Makridakis et al., *PLOS ONE* 2018; M4]. High complexity, low marginal value at your horizon. (Keep the door open only for a future microstructure/LOB model *if* you go intraday with L2 data.)
- **Max-pain as a directional target.** Real effect is ~1–2% of price moves (US, large-OI expiries only); every India-specific "evidence" is vendor anecdote with no base rate [Ni–Pearson–Poteshman for the real, small effect]. Use at most as a weak expiry-day mean-reversion prior.
- **PCR as a timing signal.** R² ≈ **0.006** versus forward index returns — essentially no linear forecasting power; it predicts *variance* better than returns [CXO review; *China Finance Review Int'l* 2019].
- **Raw OI "buildup" folklore** ("rising OI + rising price = bullish"). The academic OI signal is *negative, cross-sectional, and monthly* — the opposite framing and horizon. The directional information lives in **signed/initiated** option volume, which public OI/PCR aggregates destroy [Pan & Poteshman; Zhou].
- **Naive microstructure (OFI / VPIN / DeepLOB) at 1–5 days.** OFI's famous 65% R² is **contemporaneous, not predictive**; the predictive part decays in seconds-to-minutes and needs L2 tick data [Cont, Kukanov & Stoikov]. VPIN as a forecaster is disputed. These belong to *intraday execution*, not multi-day direction.

---

## 4. The option-chain truth: what the platforms compute vs. what predicts

You asked me to study Sensibull, screener.in, and the algo platforms ("tred code" — I read this as Tradetron / Streak / Trendlyne). Here is the honest separation of **computation** (which they do fine) from **predictive value** (mostly marketing).

**Sensibull** computes the option chain correctly: OI distribution, PCR, max-pain, IV, IV-percentile, probability-of-profit, full Greeks. The *math* is right. The *implied predictive value* of max-pain and PCR is the marketing layer — see Tier C above. **Use Sensibull-style analytics as feature inputs and as a sanity/visualization layer, not as a source of directional alpha.**

**screener.in** is the best free fundamentals screener (financials, ratios, results). For your horizon (intraday–5 day), fundamentals are **largely irrelevant** — with one exception worth a feature: **post-earnings-announcement drift** and the event window itself (which is really a VRP/IV-crush play). Don't build a fundamentals-driven intraday signal; do use the **results calendar** as an event flag.

**Tradetron / Streak / Trendlyne / TradingView** are strategy-builder/backtest tools. Useful for prototyping, but their headline backtest numbers omit slippage and downtime — AlgoTest's own comparison concedes "backtests don't include real slippage." **Treat any CAGR from these as an upper-bound fiction until re-tested under your cost model and gate.**

**The pivot:** move the option-chain layer from *"predict NIFTY direction from PCR/max-pain"* (folklore) to *"harvest the variance risk premium, vol-regime-scaled, around events and overnight, with explicit tail budgeting"* (the one thing that's real). That is both more honest and more original than what every option-chain dashboard in India sells.

---

## 5. Indian structural edges — and a regime-break warning that affects your backtests

| Edge | Verdict | How to use |
|---|---|---|
| **Variance risk premium** (short premium) | **Real, peer-reviewed** | Core vol alpha; overnight-loaded; tail-budgeted; BANKNIFTY≠NIFTY |
| **Event IV-crush** (RBI / Budget / earnings) | Real *mechanism*, but crowded & fat left tail | Same VRP; size down, define max loss, don't sell naked into events |
| **Market intraday momentum** | Real *conditional* edge | Intraday only; high-vol/high-volume days; needs intraday data |
| **Opening-range breakout** | Regime-dependent, decaying | Only with a strict volatility-regime filter; assume vendor backtests are optimistic |
| **Max-pain pinning** | Weak/contested for direction | At most a weak expiry-day prior |
| **PCR / raw OI direction** | Folklore at this horizon | Features only, never headline |

**The regime-break warning (important, current, and it hits your BankNifty target directly):** Two SEBI changes reshaped the F&O landscape, and your backtests must respect both. **(1)** From **November 2024**, each exchange may run a weekly option on only *one* benchmark index — so NSE weeklies are now **NIFTY-only**, and **BANKNIFTY, FINNIFTY and Midcap weekly options were discontinued (BankNifty options are now monthly-expiry only)**. **(2)** From **1 September 2025**, NSE expiry moved from **Thursday to Tuesday**, while **BSE (SENSEX) sits on Thursday**. Practical consequences: any pre-Nov-2024 BankNifty *weekly* backtest describes a product that no longer exists; any pre-Sep-2025 expiry-day or pinning study is contaminated by the day-of-week change. Your current evidence window (Sep–Nov 2025) is post-both-shifts and clean — but multi-year history must treat these as **explicit regime breaks**, or the gate will certify a ghost. **This reshapes your stated targets:** short-horizon *weekly-options* plays now exist for **NIFTY (Tue)** and **SENSEX (Thu)**; **BankNifty short-horizon options work is monthly-expiry only** — plan its signals and tail budgeting around monthly, not weekly, expiries. (Sources: SEBI circular / Ventura, Arihant, Kotak summaries — see Sources.)

---

## 6. Data — what you have, what to buy, what each unlocks

Your audit's own prescription was right: **the unlock is more history, not a new model.** Here's the concrete stack.

**Free / EOD layer (start here, today):**
- **NSE F&O settlement / UDiFF files + index/stock EOD.** Note: the legacy combined F&O *bhavcopy CSV was discontinued ~8 July 2024* — you now stitch the UDiFF / daily-settlement files, and there's a schema seam pre/post-2024 to handle. Mirrors: GetBhavcopy, `jugaad-data`, `nsepython`.
- **India VIX history** (since 2008, free CSV) — feeds calibration and vol-regime.
- **NSE option-chain JSON snapshot** — *live snapshot only*; you must **poll-and-store** to build your own intraday OI/IV history. This is the single most valuable thing to start recording immediately, because brokers don't give per-strike OI/IV history.
- **FII/DII + participant-wise OI** (NSE) — the F&O participant-positioning file is the higher-signal one.

**Broker API (cheap workhorse — pick one):**
- **Zerodha Kite Connect** — ₹500/mo per key; candle history (1-min in 60-day chunks back several years), WebSocket ticks; most battle-tested.
- **Upstox** — API free, history back to 2005, WebSocket V3.
- **Angel One SmartAPI** — free, up to 8,000 candles/request, tick WebSocket.
- **Dhan** — data API ~₹499/mo, ~5 yrs intraday.
- *Caveat:* all give your own tick capture going forward + candle backfill, but **historical per-strike option OI/IV is thin-to-absent** — record it live from day one.

**Paid options-history feed (the one real spend — get quotes):**
- **TrueData** — Velocity desktop ~₹1,440–2,800/mo per segment + tick add-ons; live option chain *with Greeks*; "Market Replay." API is contact-priced.
- **Global Datafeeds (GFDL)** — sales-gated; has a dedicated OptionChain API and `GetHistoryGreeks`. Budget roughly **₹2,000–6,000/mo** for usable options history.

**News / events:** GDELT (free, 15-min global news/tone) + NSE/BSE corporate-actions & results calendar (free, authoritative).

**Fundamentals (secondary):** screener.in free core (Premium ~₹5–7k/yr for export); Trendlyne ~₹5,900/yr if you need bulk download + FII/DII history.

**What I need *you* to procure or decide** (so the build isn't blocked):
1. **One funded broker API key** (Kite ₹500/mo recommended, or free Angel/Upstox) — enables live recording + intraday backfill.
2. **A written quote from TrueData *and* GDFL** for historical options-with-Greeks — both are sales-gated; we need real numbers to choose.
3. **Confirmation of your compute** (a single modern machine with a GPU is plenty — we are GBM-first, not deep-net-first).
4. **Access to the existing Anvil repo** so the build extends it rather than rebuilds.

---

## 7. The honest scoreboard (retire "accuracy" as the headline)

Replace the single accuracy number with a five-part scorecard, all out-of-sample, all net of your cost model:

1. **Post-cost edge per trade** with **Harvey t ≥ 3** and **Deflated Sharpe ≥ 0.95** (your gate — keep it).
2. **Calibration**: Brier score + reliability curve; stated p must equal realized frequency.
3. **Conditional accuracy at coverage**: the risk–coverage curve — "X% correct on the top Y% most-confident signals." *This is your honest "70%."*
4. **Tail / skew**: max drawdown, CVaR, worst-trade — so a short-vol book can't hide its steamroller.
5. **Abstention rate**: how often the engine correctly says "no edge today." A feature, not a bug.

---

## 8. Bottom line — the 5 highest-ROI moves, ranked

1. **Fetch multi-year NSE F&O history and re-run the existing gate.** Zero new modeling; this is what turns "0 cells edge-verified" into real certifications. (Your audit said this; it's right.) *Unlocks: everything downstream.*
2. **Add the selective-prediction + meta-labeling layer** on top of the existing quant signals — the legitimate route to high *conditional* accuracy. *Data: what you have.*
3. **Add the calibration/conformal honesty layer** so the live reliability curve tracks the diagonal and coverage is always reported. *Data: what you have.*
4. **Re-point the options layer to variance-risk-premium harvesting** (vol-regime-scaled, event/overnight-aware, tail-budgeted) instead of PCR/max-pain direction. *Data: option-chain history (record live now; buy history).*
5. **Add HAR-RV-driven regime gating and sizing**, with BANKNIFTY and NIFTY modeled separately. *Data: intraday bars for realized vol.*

Do these in order. Notice what is *not* on the list: a bigger neural network, more option-chain "indicators," or a higher accuracy headline. The wins are in **gating, calibration, leak-proof validation, and harvesting the one real premium** — exactly the unglamorous, diligence-surviving machinery that is your actual moat.

> **One honest caveat I owe you:** I cannot promise these moves reach any specific number — that's the whole point of the gate. What I can say with confidence is that they are the highest-evidence levers available, that they will improve *post-cost expectancy and calibration* materially, and that they can produce legitimately high *conditional* accuracy. If after multi-year certification the post-cost edge is still ~0, that is the market telling you the truth, and the right response is to abstain more — which your engine, uniquely, already knows how to do.

---

## Sources (highest-credibility first)

**Accuracy ceiling & overfitting**
- Validating weak-form efficiency with ML (52% mean accuracy) — https://arxiv.org/pdf/1909.05151
- Gu, Kelly & Xiu, *Empirical Asset Pricing via Machine Learning*, RFS 2020 — https://dachxiu.chicagobooth.edu/download/ML.pdf
- CSI-300 index-futures rules vanish after costs — https://arxiv.org/pdf/1710.07470
- Bailey, Borwein, López de Prado & Zhu, *Pseudo-Mathematics & Financial Charlatanism*, Notices of the AMS 2014 — https://www.ams.org/notices/201405/rnoti-p458.pdf
- López de Prado, *10 Reasons Most ML Funds Fail* — https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf
- Kapoor & Narayanan, *Leakage & reproducibility crisis in ML science*, Patterns 2023 — https://www.sciencedirect.com/science/article/pii/S2666389923001599
- Harvey, Liu & Zhu, *…and the Cross-Section of Expected Returns* (t>3), RFS 2016 — https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF
- Hou, Xue & Zhang, *Replicating Anomalies*, RFS 2020 — https://www.nber.org/system/files/working_papers/w23394/w23394.pdf

**Method families**
- Gao, Han, Li & Zhou, *Market Intraday Momentum*, JFE 2018 — https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351
- Moskowitz, Ooi & Pedersen, *Time Series Momentum*, JFE 2012 — https://www.sciencedirect.com/science/article/pii/S0304405X11002613
- Corsi, *A Simple Approximate Long-Memory Model of Realized Volatility* (HAR-RV) — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=626064
- Cont, Kukanov & Stoikov, *The Price Impact of Order Book Events* — https://arxiv.org/pdf/1011.6402
- Zhang, Zohren & Roberts, *DeepLOB* — https://arxiv.org/pdf/1808.03668
- Grinsztajn, Oyallon & Varoquaux, *Why tree-based models still outperform deep learning on tabular data*, NeurIPS 2022 — https://arxiv.org/abs/2207.08815
- Makridakis et al., *Statistical vs ML forecasting*, PLOS ONE 2018 — https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0194889

**Selective prediction / meta-labeling / calibration**
- *Trading via Selective Classification* — https://arxiv.org/pdf/2110.14914
- Meta-labeling OOS replication (Hudson & Thames) — https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/
- Sequential Predictive Conformal Inference — https://arxiv.org/pdf/2212.03463
- Temporal Conformal Prediction (finance) — https://arxiv.org/pdf/2507.05470
- CPCV reduces backtest-overfitting probability — https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110

**Indian option-chain & structural edges**
- Bajaj/Bansal et al., *Dynamics of the Variance Risk Premium: Evidence from India*, IREF 2020 — https://www.sciencedirect.com/science/article/abs/pii/S1059056020301222
- Bhat, *Asymmetry in day & night option returns: an emerging market*, J. Futures Markets 2024 — https://onlinelibrary.wiley.com/doi/10.1002/fut.22512
- Zhou, *Why does option open interest predict stock returns?* — https://acfr.aut.ac.nz/__data/assets/pdf_file/0004/686830/1b-Yi-Zhou.pdf
- Predictive power of put-call ratios (R²≈0.006) — https://www.cxoadvisory.com/sentiment-indicators/predictive-power-of-put-call-ratios/
- SEBI/NSE expiry-day change (1 Sep 2025) — https://nsearchives.nseindia.com/content/circulars/FAOP68747.pdf
- Expiry shift summary (NSE→Tue, BSE→Thu) — https://www.venturasecurities.com/blog/changes-in-expiry-nse-and-bse/ · https://www.arihantplus.com/blogs/market-updates/tuesday-is-the-new-thursday-nse-and-bse-expiry-shift-from-sep-2025 · https://www.kotakneo.com/news/market-news/sebi-to-end-thursday-expiry/
- NSE discontinues BankNifty/FinNifty/Midcap weekly options (Nov 2024) — https://newsonair.gov.in/nse-to-discontinue-weekly-index-derivatives-for-bank-nifty-nifty-midcap-select-nifty-financial-services

**Validation toolkit**
- Bailey & López de Prado, *Deflated Sharpe Ratio* — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Bailey, Borwein, López de Prado & Zhu, *Probability of Backtest Overfitting* — https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253
- White, *A Reality Check for Data Snooping*, Econometrica 2000
- Hansen, *A Test for Superior Predictive Ability*, JBES 2005

**Data sources**
- NSE All Reports (Derivatives / UDiFF) — https://www.nseindia.com/all-reports-derivatives
- Zerodha Kite Connect — https://kite.trade · Upstox — https://upstox.com/developer · Angel SmartAPI — https://smartapi.angelbroking.com/docs
- TrueData pricing — https://www.truedata.in/price · Global Datafeeds — https://globaldatafeeds.in/apis/
- GDELT — https://www.gdeltproject.org/

*Note on credibility: peer-reviewed and official-exchange sources are treated as high-confidence; practitioner/vendor figures (costs, some India-specific claims) are flagged as indicative and should be confirmed by direct quote. Several "high-accuracy" NIFTY papers were examined and rejected as level-prediction or leakage artifacts.*
