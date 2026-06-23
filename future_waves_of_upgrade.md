# Anvil — Future Waves of Upgrade (living backlog)

> See `next_wave.md` for the current top priority. Append here, never drop.

## Done
- **W1** — never-empty predictions, single-stock tips, rich Tips UI, live wiring, gated event factor, revalidate. (284 tests green.)

## Current
- **W2** — Decision-Brief engine (probability-of-touch, environment-gated). See `next_wave.md`.

## Next waves (ordered)
- **W2.5 VALIDATION / DATA** — heavy multi-year NSE bhavcopy + BSE bhavcopy (SENSEX/BANKEX); full history for equity OHLC, India VIX, FII/DII, participant-OI, earnings → **validate** the W2 touch/VRP/regime cells through `validate_cells` so `edge_verified ✓` can light up. This is the wave that converts the honest analytics into proven edge.
- **W3 STOCK STRUCTURAL** — touch-prob + VRP + regime per single stock (largecap/midcap/bluechip) on the equity OHLC; cross-sectional → index aggregation.
- **W4 ML META-LAYER** — LightGBM (py3-none wheel installs on 3.14; native Booster API, numpy-only) as a *meta-layer* over the structural targets, NOT a direction oracle: consumes touch/VRP/regime + **path/dynamics features** (ΔIV-rank, ΔGEX, OI velocity, term-slope changes, RV trajectory) → calibrated **act/abstain** (López de Prado meta-labeling) + isotonic/Platt calibration + conformal bands. Pure-numpy logistic fallback. Gated by the same DSR/PBO/t≥3 battery.
- **W5 NEWS / SENTIMENT** — pandas-free news ingestion (RSS/GDELT/exchange filings) → leak-safe per-stock/index sentiment features.
- **W6 AI RESEARCH LOOP** — LLM proposes candidate features/hypotheses → sandboxed code-gen → the existing harness validates → only measured-edge features promoted; feature leaderboard; auto-retire decayed features.
- **W7** ensemble / regime stacking · **W8** transparency leaderboard UI · **W9** intraday (Upstox instrument master, licensed minute data).

## Parked / out of scope
- **LLM-via-claude-CLI explanations** — polish only; never load-bearing, never multi-user (ToS), deterministic narrator is the always-on default.
- **Monetization** — OUT (owner: flat-free, all features free). Do not raise.
- **Daily-direction prediction** — wrong target for a buyer (red-team). Direction, if ever revived, is a last-priority regime-conditioned *abstaining* signal only.

---

## Research briefings (cited — keep for reference)

### Honest accuracy ceiling
OOS daily directional accuracy ~53–57%; >60–80% almost always = leakage/overfit. Cross-sectional long-short more achievable. (Gu/Kelly/Xiu RFS 2020; Jiang/Kelly/Xiu JF 2023; lambdafin; multiple 2024-26 surveys.)

### Probability-of-touch
P(touch K before T) ≠ terminal prob; ≈ 2× P(terminal beyond) for an ATM-forward barrier (reflection principle), breaks otherwise. Compute via GBM Monte-Carlo at implied vol + **Brownian-bridge correction** for discrete monitoring (Beaglehole–Dybvig–Zhou). Risk-neutral overstates real touch → **VRP-adjust** (scale vol by realized/implied). Every strike×horizon×day is a separately-resolvable touch/no-touch label → large calibration sample. (tastytrade POP; barrier-option literature.)

### VRP / realized-vol forecasting (pure-numpy)
Implied vol > realized on average → buying premium structurally -EV except rare windows. Forecast RV without GARCH: **HAR-RV** (np.linalg.lstsq over RV 1d/5d/22d), **EWMA/RiskMetrics**, and **range estimators** Parkinson / **Garman-Klass** / Rogers-Satchell / Yang-Zhang (several× more efficient than close-to-close). VRP = IV − E[RV]; record as a probability (P(realized<implied)) to calibrate. (JFM 2025 VRP; range-estimator literature.)

### Event IV-crush + regime
Earnings IV crush 30–60% overnight; index events (RBI/Budget) 30–50%; **term-structure backwardation (front IV > back IV) → imminent event → abstain from buying premium**; expected move ≈ 0.85×ATM straddle (~70–75% containment). Regime via **pure-numpy rules ensemble** (RV-vs-MA, IV term slope, ADX, lag-1 autocorr, GEX sign, vol-of-vol) — present as **agreement count, never an accuracy %** (no ex-post look-ahead labels). HMM not used (`hmmlearn` no cp314 wheel; rules ≥ HMM here). CUSUM for change-points. (Baltussen et al. JFE 2021; SpotGamma; volatilitybox; Amberdata term-structure.)

### India data sources (pandas-free: httpx + stdlib json/csv)
- Equity/index OHLC + India VIX: **Yahoo chart JSON** `query1.finance.yahoo.com/v8/finance/chart/{SYM}.NS|^NSEI|^NSEBANK|^INDIAVIX?range=2y&interval=1d` (epoch→IST, key by NSE trading date, reconcile vs nse_eod, fail loudly on gaps).
- Multi-year NSE F&O/cash bhavcopy: `nsearchives.nseindia.com/.../BhavCopy_NSE_FO_..._{YYYYMMDD}_F_0000.csv.zip` (+ legacy); BSE for SENSEX. Best-effort, cache.
- VIX/FII-DII/participant-OI/constituents/earnings: NSE official reports + nsepython; earnings calendars (TheCore XBRL, NiftyTrader, NSE corporate filings). Gentle rate-limit.
- Deps: `arch`/`hmmlearn` have NO cp314 wheels → stay pure-numpy. LightGBM has a `py3-none` wheel (for W4).
