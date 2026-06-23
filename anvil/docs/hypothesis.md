# Anvil: A Merged Technical Blueprint for Directional Prediction of Indian Index Options & Single Stocks

## TL;DR
- **70%+ sustained directional accuracy on liquid Indian indices is NOT honestly reachable on a raw, all-trades basis.** The best peer-reviewed evidence puts raw next-day index direction at ~53–60% out-of-sample; the headline 70–80% figures in Plan B are either rule-recovery artifacts, leakage-prone, or unsourced. Plan A's thesis (~50–55% raw) is essentially correct and should anchor the product.
- **Selective abstention CAN push accuracy into the mid-to-high 60s on a small gated subset (roughly 8–15 signals/month), but only if calibration is real and the subset is chosen by genuine confidence, not hindsight.** A defensible stretch target is ~62–68% on the gated ~10–20% of opportunities; brief, regime-specific windows (expiry-day gamma, event IV-crush) may touch ~70% but degrade fast under regime shift and multiple testing.
- **The honest, sellable, and regulation-safe edge is calibrated probabilities with a public reliability curve (Brier score, reliability diagram, coverage bands)** — fusing dealer-positioning, the Breeden-Litzenberger risk-neutral density, and regime reads — NOT accuracy claims. Build the architecture to test every paradigm empirically and let out-of-sample calibration pick winners.

## Key Findings

### 1. The achievable frontier
- Peer-reviewed raw index direction prediction clusters at 53–60%. Jiang, Kelly & Xiu's "(Re-)Imag(in)ing Price Trends" (*The Journal of Finance*, 2023, Vol. 78, No. 6, pp. 3193–3249, DOI 10.1111/jofi.13268) — the flagship image-based study — reports out-of-sample directional accuracy "in excess of 53%" for monthly stock returns and frames the value as "small gains of even 1% to 2%." The model "put[s] all stocks' past price data on the same scale" to make "cross-sectional inferences regarding future directional price moves." A CNN study on the S&P 500 reports "over 55%." A 2025 ensemble paper states most systems "struggle to exceed 55–57%" and reaches 60.14% at best.
- For India specifically, a published parallel-CNN model fusing news text + prices + technicals reports 74.96% (Nifty 50), 69.83% (Nifty Next 50) and 71.23% (Nifty Bank) — but these are full-sample text-augmented results vulnerable to look-ahead/leakage and are not walk-forward gated live numbers; treat as optimistic ceilings, not deployable expectations.
- Selective classification theory (Chow 1957; El-Yaniv & Wiener 2010; Geifman & El-Yaniv SelectiveNet 2019) confirms that abstention trades coverage for accuracy along a risk-coverage curve — but only up to an oracle bound, and the gains "deteriorate under covariate shift," precisely the non-stationary regime of markets. So gating buys real accuracy, but less than naive backtests imply, and it collapses exactly when regimes change.

### 2. Paradigm audit — what's real vs hype
- **Options-chain-as-image CNN/ViT (Plan B claim 1): NO real source.** A dedicated subagent search across arXiv, SSRN, ScienceDirect, Springer, RePEc found NO paper feeding a rendered options chain/IV-surface image to a CNN/ViT to predict SPX next-day direction at 70–75%. The closest real work (IV-surface CNN, e.g. SFI RP 23-60; SSRN 5170265; arXiv 2511.03046) predicts cross-sectional stock returns or realized volatility — not index direction — and reports Sharpe/alpha or RV error, never a 70–75% directional figure. The 70–95% figures that circulate trace to Cohen/Balch/Veloso (2019), which recovers known technical-indicator rules from candlestick images and "does not predict returns." This Plan B claim is essentially fabricated.
- **LightGBM/GBM on tabular features (Plan B claim 2): partially real but overstated.** GBMs are legitimate and strong on tabular market features, and Indian LightGBM index studies exist; but published high accuracies are regression RMSE/R² results, not gated 68–72% Bank Nifty directional numbers. Keep as a core engine; expect ~55–60% raw, not 68–72%.
- **GEX / dealer gamma (Plan B claim 3): real for SPX, UNVALIDATED for India, and structurally suspect there.** Baltussen, Da, Lammers & Martens (*Journal of Financial Economics*, Vol. 142, Issue 1, Oct 2021, pp. 377–403) provide peer-reviewed evidence: "Hedging short gamma exposure requires trading in the direction of price movements, thereby creating price momentum... The return during the last 30 minutes before the market close is positively predicted by the return during the rest of the day (from previous market close to the last 30 minutes)" — based on "over 60 futures on equities, bonds, commodities, and currencies between 1974 and 2020." This is a genuine, citable mechanism. BUT SqueezeMetrics/SpotGamma GEX is SPX-specific. India's structure differs: Bank Nifty weekly options turnover dwarfed cash by ~350:1 on Jan 17, 2024; the market is heavily retail-and-prop-driven; and the Jane Street case shows expiry-day index levels can be driven by large directional players, not classic delta-neutral dealer hedging. GEX-style dealer-positioning signals must be re-derived and re-validated from scratch on Indian data; do not assume SPX mechanics transfer.
- **Breeden-Litzenberger risk-neutral density (Plan A claim 3): real and underused.** B-L (1978) extracts a model-free risk-neutral PDF from option prices; it is a genuine market-implied expectation and a strong calibration input. Caveat: it is risk-neutral (not real-world) and noisy in the tails; use as a feature/prior, not a forecast.
- **Black-76 on futures (Plan A claim 4): correct and non-negotiable.** Indian index options are European and futures-referenced; Black-76 on the forward/futures is the right model, not Black-Scholes on spot. Industry Indian tooling (e.g. OpenAlgo) already uses Black-76 (py_vollib).
- **FinBERT / sentiment (Plan B claim 4): real but weak standalone.** Published FinBERT ROC-AUC ~0.66 and mid-range probabilities cluster near 0.50 — consistent with 55–60% standalone at best. Useful as an ensemble feature; Indian-language/Indian-news fine-tuning is thin and a real gap.
- **Order-flow imbalance (Plan B claim 5): real at very short horizons.** Cont, Kukanov & Stoikov show near-linear OFI→short-horizon price relationship; DeepLOB-style models work intraday. Effect is strongest in large-tick instruments and decays in seconds-to-minutes; 60–65% at a 15-min horizon is plausible intraday but needs L2 depth data.
- **HMM regime-switching (Plan B claim 6): real as a gate, not a predictor.** Well-established for regime detection/risk-gating (Hamilton 1989; QuantStart SPY example). Use to gate/size, not to predict direction.
- **Ensemble stacking (Plan B claim 8): real, modest.** 5–7 genuinely uncorrelated models improving accuracy 3–7% is plausible IF the models are truly decorrelated; in practice correlation is high and gains are smaller.
- **Calibration / Brier / isotonic-Platt (Plan A claim 2): the actual product.** Good models score Brier 0.1–0.2; isotonic regression (PAV) and the CORP reliability-diagram method (PNAS 2021) are the right tools. Calibration improves Brier/log-loss without harming ranking. This is the defensible core.

### 3. India-specific realities
- **Retail loss statistic:** SEBI's July 2025 "Comparative Study of Growth in Equity Derivatives Segment vis-à-vis Cash Market After Recent Measures" (covering ~96 lakh unique traders from the top 13 brokers) found 91% of individual F&O traders lost money, with net losses rising 41% YoY to ₹1,05,603 crore in FY25 (from ₹74,812 crore in FY24); average per-person loss ₹1.1 lakh. Unique individual traders fell from 61.4 lakh (Q1 FY25) to 42.7 lakh (Q4 FY25). This is the regulatory and ethical backdrop — accuracy hype is precisely what SEBI is policing.
- **Regulatory tightening (2024–2026):** minimum contract value raised to ₹15–20 lakh (Nifty lot 25→75, later 65; Bank Nifty →30; Sensex 10→20); weekly expiries cut to one benchmark per exchange (Nifty on NSE, Sensex on BSE); Bank Nifty weeklies discontinued (Nov 2024); expiry standardized to Tuesday (NSE)/Thursday (BSE) from Sep 1, 2025; STT on options raised to 0.1% (Apr 2025); calendar-spread margin benefit removed on expiry day; intraday position-limit monitoring from Apr 2025.
- **Jane Street case:** SEBI's ex-parte interim order dated July 3, 2025 impounded ₹4,843.57 crore (~US$567M) in alleged unlawful gains; SEBI found JS Group's index-options profit was ₹43,289 crore against ~₹7,687 crore losses in stock/index futures and cash, net ~₹36,500 crore (Jan 2023–May 2025), with manipulation alleged on 18 expiry days (15 BANKNIFTY + 3 NIFTY). Jane Street deposited the sum July 14, 2025 and resumed trading July 21, 2025. This is direct evidence that Indian expiry-day index dynamics are partly engineered by large players — a warning against importing SPX dealer-hedging assumptions.
- **Algo framework:** SEBI's Feb 2025 circular (phased through 2025, full compliance ~April 2026) makes brokers principals and algo providers agents; bans open APIs; mandates unique Algo-IDs, static-IP whitelisting, 2FA; black-box algos require a Research Analyst license. This directly constrains how Anvil can be distributed and what can be claimed/sold.
- **Data vendors:** TrueData and Global Datafeeds (GDFL) are NSE/BSE-authorized for tick/minute/options-chain+Greeks; broker APIs (Dhan, Upstox, Zerodha Kite, Angel SmartAPI) for live+historical minute but typically non-redistributable. AlgoTest provides minute-level options data. Budget for licensed feeds for any production/redistributed product.

## Details

### Verdict on the 70%/80% question
80%+ averaged directional accuracy on liquid Indian indices is not honestly attainable and any claim of it should be treated as a red flag (leakage, multiple testing, or rule-recovery). 70%+ is not attainable on a raw all-trades basis. On a genuinely confidence-gated subset, ~62–68% is a defensible stretch; isolated structural windows (last-30-min expiry-day gamma momentum à la Baltussen et al.; event IV-crush filtering) may briefly reach ~70% but cannot be averaged across all signals and will mean-revert. Selective abstention buys accuracy by sacrificing coverage and by concentrating on structurally predictable states — it cannot manufacture edge where none exists, and it degrades under regime shift.

### Keep / Kill / Graft table
- **Options-chain-as-image CNN/ViT — KILL** (as a headline direction engine; no evidence). GRAFT only the legitimate variant: IV-surface CNN/ViT as a volatility/feature extractor.
- **LightGBM/XGBoost/CatBoost tabular — KEEP** (core engine; expect 55–60% raw).
- **LSTM/TCN/Transformer time-series — KEEP as candidates**, but only if they beat GBM on purged walk-forward; usually marginal.
- **GEX/dealer gamma — GRAFT, re-validate** (cite Baltussen for the mechanism; re-derive on Indian data; do not import SqueezeMetrics levels).
- **Breeden-Litzenberger RND — KEEP** (calibration prior + feature).
- **Black-76 Greeks — KEEP** (mandatory).
- **FinBERT/sentiment — GRAFT** (ensemble feature; fine-tune on Indian news).
- **Order-flow imbalance — KEEP for intraday** (needs L2 data).
- **HMM regime-switching — KEEP as a gate**, not a predictor.
- **Ensemble stacking/meta-learning — KEEP** (modest, real gains).
- **Isotonic/Platt calibration + Brier optimization — KEEP as the spine.**

### Recommended architecture (empirical-freedom-first)
1. **Data & Greeks layer:** licensed tick/minute + options chain (TrueData/GDFL); Black-76 Greeks on futures; B-L RND extraction; OFI from L2.
2. **Feature/engine zoo:** GBMs, time-series nets, IV-surface CNN, sentiment, OFI, dealer-positioning proxies — all as interchangeable candidates.
3. **Regime gate:** HMM/regime classifier conditions which engines are trusted.
4. **Stacking meta-learner** combines engine outputs.
5. **Calibration layer:** isotonic/Platt → calibrated probability; CORP reliability diagram + Brier monitored continuously.
6. **Selective-prediction layer:** abstain below a confidence/coverage threshold tuned on the risk-coverage curve.
7. **Empirical-tournament harness:** every paradigm competes on purged/embargoed walk-forward and Deflated Sharpe; winners are chosen by out-of-sample calibration, not a priori belief. The builder retains maximum latitude to add engines inside and outside this list.

### Non-negotiable validation protocol
- Purged + embargoed walk-forward CV and Combinatorial Purged CV (López de Prado); never plain k-fold.
- Deflated Sharpe Ratio (Bailey & López de Prado 2014) and Probability of Backtest Overfitting, reporting the number of trials.
- Harvey et al. t-stat hurdle of 3.0, not 2.0, for any new signal.
- Realistic Indian F&O cost model: STT 0.1% on options, brokerage, exchange fees, slippage, market impact, plus the new lot-size/margin regime.
- Adversarial validation for train/live drift; continuous reliability-curve monitoring in production.

### Framing honestly
Sell calibration, not accuracy: "When Anvil says 65%, it is right ~65% of the time," shown on a live public reliability diagram with coverage. This is both more defensible and SEBI-RA-compatible than an accuracy headline.

## Recommendations
1. **Stage 0 (foundations):** license TrueData/GDFL; implement Black-76 Greeks + B-L RND; build the purged-walk-forward + DSR harness FIRST. Benchmark: any engine must beat a 53% naive and clear DSR before promotion.
2. **Stage 1 (raw engines):** ship GBM + regime gate; target honest 55–60% raw, fully calibrated (Brier < 0.24, reliability curve near-diagonal).
3. **Stage 2 (selective layer):** add abstention; publish the risk-coverage curve; target 62–68% on ~10–20% coverage (~8–15 signals/month). Threshold to change course: if gated accuracy doesn't clear ~62% out-of-sample on ≥6 months live, cut coverage further or abstain entirely in that regime.
4. **Stage 3 (India dealer-positioning R&D):** re-derive GEX-style signals on Indian data; validate against Baltussen-style expiry-day momentum; keep only if they add calibrated lift.
5. **Always:** frame as calibrated probabilities; comply with the algo/RA framework; never advertise 80%.

### Genuinely novel angles worth testing
- Regime-conditional selective prediction fused with the B-L risk-neutral density (predict only when the implied distribution and the regime read agree).
- Cross-sectional single-stock signals aggregated to the index (Bank Nifty's ~5-stock, ~82%-weight concentration makes this tractable).
- Event/expiry-cycle-specific models exploiting the new Tuesday/Thursday standardization and weekend-decay shift.
- IV-crush-aware event filtering to abstain around earnings/RBI/budget events where premium dynamics dominate direction.

## Caveats
- India-specific GEX behavior is unvalidated and structurally different from SPX; the Jane Street case shows index expiry levels can be driven by large players, not textbook dealer hedging — treat any India dealer-gamma signal as research-grade until proven.
- The Indian text-augmented CNN accuracies (71–75%) are not walk-forward gated live results and likely embed look-ahead; do not anchor expectations on them.
- All "70%+" claims in Plan B failed the evidentiary test; the options-chain-as-image claim has no real source at all.
- Selective-prediction gains erode under regime shift — the exact condition markets exhibit; size accordingly.
- SEBI regulation is actively tightening; distribution model and marketing claims carry real legal risk under the algo and Research Analyst frameworks.