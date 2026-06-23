# Anvil — Phase 1 Operator Runbook (data unlock + always-on recorder)

The Phase-1 *machinery* is built, tested, and (where possible) already run. The three tasks below need
**your machine** (a live broker token, market hours, or a multi-hour anti-bot pull), so they run on your
Windows box, not in the build environment. Replace `C:\path\to\anvil` with your repo path and
`PY=.venv\Scripts\python.exe`.

> One-time per trading day: refresh the broker token before the open — Upstox/Kite tokens die ~03:30 IST.
> `…\%PY% -m anvil.cli auth upstox` (then set `ANVIL_PRIMARY_SOURCE=upstox` in your `.env`).

---

## 1. Always-on intraday recorder  ← the time-urgent one (per-strike OI/IV is unbuyable)

Records every chain snapshot during the IST session; exits at 15:30; Task Scheduler relaunches next
trading day. Holiday-aware (skips `data/nse_holidays.csv` dates), token-aware (waits if no live token).

```bat
schtasks /Create /TN "Anvil Recorder" /SC DAILY /ST 09:10 /F ^
  /TR "cmd /c cd /d C:\path\to\anvil && set ANVIL_PRIMARY_SOURCE=upstox&& .venv\Scripts\python.exe -m anvil.cli record run --underlyings NIFTY,BANKNIFTY,SENSEX --cadence 60"
```
Smoke-test it now (offline, no token): `%PY% -m anvil.cli record run --source demo --force-open --once`.

## 2. 24-month NSE F&O backfill  ← one-off, resumable

Hardened (resume / retry+backoff / polite rate-limit). Validated against the real NSE archive on a
legacy sample here; the full pull is ~500 requests, so run it from your IP. Re-run if interrupted — it
skips what's already cached.

```bat
%PY% -m anvil.cli data backfill --years 2 --cache-dir data\bhavcopy_cache --workers 3
```
Then confirm integrity: `%PY% -m anvil.cli data health` (reports gaps + reconciles close sources).

## 3. EOD "moat clock"  ← accrues the live reliability curve

After the close, snapshot + resolve forecasts + issue/resolve tips + revalidate the gate; pull the
day's positioning feed.

```bat
schtasks /Create /TN "Anvil EOD Clock" /SC DAILY /ST 16:00 /F ^
  /TR "cmd /c cd /d C:\path\to\anvil && .venv\Scripts\python.exe -m anvil.cli ledger run-daily NIFTY,BANKNIFTY --full && .venv\Scripts\python.exe -m anvil.cli data fetch-positioning"
```

---

## Maintenance
- **Holidays:** refresh `data/nse_holidays.csv` from the exchange's official list each year (drives the
  recorder/backfill/health gating).
- **Events/earnings:** update `data/events.csv` (RBI/Budget) and `data/earnings.csv` (results dates) each
  quarter — these gate the VRP / IV-crush windows.
- **Health:** `anvil data health` exits non-zero on a reconciliation **integrity failure** (two close
  sources disagree > 1.5%) — investigate before trusting that day's data.

## Deferred (intentionally) to later phases
- **Regime-break cell-keying.** `live/trading_calendar.py` ships the metadata + helpers (`expiry_regime`,
  `weekly_discontinued`, `expiry_weekday`) and tests; consuming them in the backtest **cell key** (so a
  cell never pools across the 2024-11 weekly-discontinuation or the 2025-09 Thu→Tue shift) lands in
  **Phase 3 (Gate-0 re-certify)**, where multi-year history makes it bite. On the current post-break
  cache it has no effect, so wiring it now would add risk for no benefit.
- **BSE/SENSEX bhavcopy ingestor** — deferred per decision; SENSEX is closes-only + live-recorded for now.
