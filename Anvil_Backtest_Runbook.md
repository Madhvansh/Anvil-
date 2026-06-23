# Anvil — Backtest Runbook (see how it works on test data)

How to fetch more history and re-run Anvil's **walk-forward, out-of-sample** backtest yourself,
read every number it prints, and understand exactly what it takes for a signal to earn the
**"Edge-verified ✓"** badge. Companion to `Anvil_Evidence_Pack.pdf`.

> **Run everything from the `anvil/` project directory.** Commands below use the `anvil` console
> script that ships in the virtualenv. On Windows PowerShell, if `anvil` isn't on your PATH, prefix
> with the venv: `.\.venv\Scripts\anvil ...` (or `.\.venv\Scripts\python -m anvil.cli ...`).

---

## 0. The mental model (your "train / test / validation")

Anvil's signals are mostly **rule-based quant** (Black-76 Greeks, cross-sectional momentum, HAR-RV),
not a fitted model — so there is **no weights "training" step** to do (the ML meta-layer is a future
wave). The honest equivalent of "test on held-out data" here is the **walk-forward backtest**:

1. For each past trading day `d`, the engine reconstructs only what was knowable on day `d`
   (look-ahead is blocked by `AsOfContext`, which raises if any code peeks at the future).
2. It issues option / single-stock tips for that day.
3. It resolves each tip on the **realized** settlement price, held to expiry, **net of modelled
   round-trip cost** — so a tip can never "win" on paper alone.
4. Outcomes are pooled into `(structure, regime, underlying)` cells and run through the
   anti-overfitting battery (CPCV + embargo, Deflated Sharpe, PBO, Harvey t ≥ 3, bootstrap).

Everything the backtest reports is out-of-sample. The single reason nothing is edge-verified today
is **sample size** — three months isn't enough independent data for the gate to certify anything.
More history is the unlock.

---

## 1. What you have now vs. what you need

| | Currently cached | What a real validation run needs |
|---|---|---|
| NSE F&O bhavcopy (options/futures EOD) | `data/bhavcopy_cache/` — **Sep 1 – Nov 28 2025** (~62 days) | 2–5 years |
| Index/stock closes + India VIX (Yahoo) | `data/closes_cache/` — **^NSEI only** | `^NSEI, ^NSEBANK, ^INDIAVIX` + each stock's `{SYM}.NS` |
| BSE bhavcopy (SENSEX) | none | not yet ingested — **SENSEX can't be backtested yet** |

---

## 2. Step 1 — fetch more history

**NSE F&O bhavcopy** (the core options/futures EOD source). Fetch in 1-year chunks; NSE is fragile and
rate-limits, so weekends are skipped automatically and any failed day is reported and skipped. Inserts
are idempotent, so just **re-run the same range to fill gaps**.

```powershell
anvil backtest fetch --start 2024-01-01 --end 2024-12-31
anvil backtest fetch --start 2025-01-01 --end 2025-11-30
# re-run any range to backfill days that errored the first time
```

**Daily closes + India VIX** (used for regime/realized-vol and honest touch resolution). Add the
index symbols and, for the equity backtest, the `.NS` symbol of each stock you'll scan:

```powershell
anvil data fetch-closes --symbols ^NSEI,^NSEBANK,^INDIAVIX --range 5y
anvil data fetch-closes --symbols RELIANCE.NS,SBIN.NS,HAL.NS,TRENT.NS --range 5y
```

Each line prints `bars=<n> span=<first>…<last> skipped=<n>` so you can confirm coverage.

---

## 3. Step 2 — run the backtest

> Tip: write the validation run to **separate DB files** with `--ledger-path` / `--store-path` so it
> never mixes with your live/demo ledger. Omit them to use the configured defaults.

### Index options
```powershell
anvil tips backtest --underlyings NIFTY,BANKNIFTY `
  --start 2024-01-01 --end 2025-11-30 `
  --min-samples 50 --max-expiries 2 `
  --ledger-path val_ledger.duckdb --store-path val_store.duckdb
```

### Single stocks (BUY/SELL momentum)
```powershell
anvil tips backtest --equities `
  --universe-size 40 --top-k 5 `
  --start 2024-01-01 --end 2025-11-30 --min-samples 50 `
  --ledger-path val_ledger.duckdb --store-path val_store.duckdb
```

### (Optional) market-implied calibration backtest
Separate from tips — records the engine's market-implied probabilities against realized outcomes, the
purest reliability-curve test:
```powershell
anvil backtest run --underlyings NIFTY,BANKNIFTY --start 2024-01-01 --end 2025-11-30
```

**Key flags**

| Flag | Meaning |
|---|---|
| `--min-samples` | resolved tips a cell needs before it's even *considered* headline-eligible (default 50) |
| `--max-expiries` | options: nearest N expiries scored per day (default 2 — short-term tips only) |
| `--universe-size` | equities: how many most-liquid F&O stocks to scan (default 40) |
| `--top-k` | equities: longs/shorts issued per day (default 5) |
| `--ledger-path` / `--store-path` | write to isolated DuckDB files instead of the defaults |

---

## 4. Step 3 — read the results

### The summary line
```
tip-backtest [NIFTY,BANKNIFTY]: issued 984  resolved 767  cells 59  headline-eligible 0  PBO 0.49
```
- **issued** — tips generated across the walk-forward.
- **resolved** — tips that reached expiry and got a realized win/loss (the rest were still open at the
  end of your data window).
- **cells** — distinct `(structure, regime, underlying)` buckets measured.
- **headline-eligible** — cells that cleared the **entire** gate. This is the number you want to grow.
- **PBO** — global probability of backtest overfitting (lower is better; the gate needs ≤ 0.5).

### The calibration / reliability view
```powershell
anvil ledger report          # look for the panel titled "Backtested · real EOD (out-of-sample)"
anvil serve                  # then open http://127.0.0.1:8011  →  Tips tab
```
The Tips tab shows the live reliability curve (predicted % vs realized %), the risk-coverage curve,
and the per-cell track record. This is the screen to show an investor.

### The raw evidence (every resolved trade)
```python
import duckdb
con = duckdb.connect("val_store.duckdb", read_only=True)

# per-cell verdicts with the full gate
con.sql("""select underlying, structure, regime_bucket, n, win_rate, mean_conviction,
                  cost_adjusted_edge, t_stat, dsr, pbo, robustness_p_low, headline_eligible
           from tip_validation order by n desc""").show()

led = duckdb.connect("val_ledger.duckdb", read_only=True)
# every individual tip: what it predicted vs what actually happened
led.sql("""select f.underlying, f.created_ts, f.resolve_ts, round(f.prob,3) pred_prob,
                  o.realized_value, o.event   -- event = 1 win, 0 loss
           from forecasts f join outcomes o on o.forecast_id=f.id
           where f.source='tip_backtest' order by f.created_ts""").show()
```
> Close the DB connections (or stop `anvil serve`) before re-running a backtest — DuckDB takes a write
> lock and a second writer will get a "permission denied / lock" error.

### How to read a per-cell row
| Column | Passes when | Plain meaning |
|---|---|---|
| `n` | ≥ 50 | enough resolved trades |
| `win_rate` vs `mean_conviction` | win_rate ≥ conviction | confidence wasn't inflated |
| `cost_adjusted_edge` | > 0 | profitable after costs (return on risk per trade) |
| `t_stat` | \|t\| ≥ 3.0 | not a fluke (Harvey hurdle) |
| `dsr` | ≥ 0.95 | survives multiple-testing deflation |
| `pbo` | ≤ 0.5 | the in-sample winner isn't overfit |
| `robustness_p_low` | > 0 | edge holds in a robust bootstrap tail |
| `headline_eligible` | all of the above at once | **earns "Edge-verified ✓"** |

A high `win_rate` alone means nothing: the 87–94% cells are short-volatility (win small often, lose
big), which is why they show `dsr ≈ 0.00` and stay ineligible. That's the gate working, not failing.

---

## 5. What it takes to light up "Edge-verified ✓"

A cell flips to `headline_eligible = True` automatically once it clears **every** column above. In
practice that needs:

1. **More independent days.** Option tips on the same day resolve together (one jump day moves every
   upside strike), so the gate counts *independent trading days*, not raw tips. Three months ≈ too
   few; 1–2+ years gets cells to `n ≥ 50` with real independence.
2. **A genuine post-cost edge** that holds out-of-sample — if it's not real, more data correctly keeps
   it dark rather than certifying noise.

Nothing about the model changes — you just feed it the history and re-run. Re-runs are deterministic
(tip IDs are content-hashed, inserts idempotent, the bootstrap is seeded), so the same range always
reproduces the same curve.

---

## 6. Caveats & troubleshooting

- **NSE fetch is best-effort.** Expect some skipped days on first pass (rate-limits, holidays). Re-run
  the same range to backfill; it won't duplicate.
- **SENSEX / BSE not supported yet** — BSE bhavcopy isn't ingested, so only NSE underlyings
  (NIFTY, BANKNIFTY, F&O stocks) will backtest.
- **DB lock errors** = something else holds the DuckDB file. Stop `anvil serve` / close any open
  connection, then retry.
- **Dependency reality** — the Python 3.14 venv runs pure-numpy (no pandas/sklearn/arch); this is
  expected and fine for the backtest.
- **After any backend code change**, restart `uvicorn`/`anvil serve` and hard-refresh the PWA
  (Ctrl+Shift+R) so the new bundle loads.
- **Sanity check before trusting a run:** `cd anvil && .venv\Scripts\python -m pytest -q` (300+ pass).

---

## 7. The 10-minute version

```powershell
cd anvil
anvil backtest fetch --start 2024-06-01 --end 2025-11-30           # ~18 months of F&O EOD
anvil data fetch-closes --symbols ^NSEI,^NSEBANK,^INDIAVIX --range 5y
anvil tips backtest --underlyings NIFTY,BANKNIFTY --start 2024-06-01 --end 2025-11-30 --min-samples 50
anvil tips backtest --equities --start 2024-06-01 --end 2025-11-30 --min-samples 50
anvil ledger report          # read the out-of-sample panel
anvil serve                  # open http://127.0.0.1:8011 → Tips tab
```

If a cell clears the gate, you'll see `headline-eligible` go above 0 and the "Edge-verified ✓" badge
appear on that tip in the UI. Until then, the honest reliability curve **is** the demo.
