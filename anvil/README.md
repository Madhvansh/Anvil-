# ⚒ Anvil — Options Intelligence for Indian Markets

**Calibrated, not "accurate."** In a market full of tipsters claiming 90% hit-rates, Anvil sells
something you can audit: probabilistic forecasts for NSE/BSE index options, each shown with a
**live, public reliability curve** and a single intuitive headline — the **Calibration Score**
(*when we say 70%, it happens ~70% of the time*). Greeks are computed locally with **Black-76 on
the futures price** (Indian index options settle off futures, never BSM on spot).

> Analytics & education only — not investment advice. Outputs are probabilities / ranges / regime
> reads, never point targets or guaranteed returns.

---

## The app

Anvil is a personal, multi-device **PWA** (React + Vite) over a FastAPI backend: a personal
login, onboarding, and a **question-organized dashboard** with **Simple / Trader / Expert** modes —
a daily brief, "where can it move" range cone, regime traffic-light, OI walls, IV/skew + IV-crush,
"what changed since yesterday", a risk tab (beta-weighted book + scenario heatmap + Monte-Carlo
P&L), a grounded copilot, natural-language alerts, and the calibration panel. Every payload carries
data **provenance** (live / backtest / demo / derived).

### Run it (offline, no keys)

```bash
# 1) backend (Python 3.11+)
python -m venv .venv && .venv/Scripts/activate        # *nix: source .venv/bin/activate
pip install -e ".[dev,app,crosscheck,copilot,schedule]"
pytest -q                                              # test suite (163 passed / 1 skipped)

# 2a) dev: API + Vite dev server (hot reload, proxied)
uvicorn anvil.api.app:app --reload                     # :8000
cd web && npm install && npm run dev                   # :5173 → open this

# 2b) or build the SPA and serve everything from FastAPI
cd web && npm install && npm run build                 # emits into anvil/api/static
uvicorn anvil.api.app:app                              # open http://127.0.0.1:8000
```

### Deploy (one box: app + Postgres + Caddy/HTTPS)

```bash
cp .env.example .env   # set ANVIL_SECRET_KEY, POSTGRES_PASSWORD, ANVIL_DOMAIN, broker keys
docker compose up -d --build
```

See **[docs/DEPLOY.md](docs/DEPLOY.md)** (Oracle Always Free / Render) and
**[docs/SECURITY.md](docs/SECURITY.md)**. The CLI (`python -m anvil.cli …`) still works for the
calibration loop and scripting.

## The calibration loop (the moat)

The reliability curve is built **only from real, resolved forecasts**. Two sources feed it, kept
strictly separate from any synthetic/demo data:

```bash
# 1) Real out-of-sample backtest from NSE/BSE EOD F&O bhavcopy history
anvil backtest fetch --start 2025-01-01 --end 2025-06-30 --cache-dir data/bhavcopy_cache
anvil backtest run   --underlyings NIFTY,BANKNIFTY     --cache-dir data/bhavcopy_cache

# 2) Start the live forward track record (run daily after the cash close)
anvil ledger run-daily NIFTY,BANKNIFTY --source upstox
anvil ledger run-daily NIFTY --realized 24011.5        # resolve a settled expiry at its close
anvil ledger report                                    # both curves + Calibration Scores
```

Schedule the daily run on Windows so the track record accrues automatically:

```bat
schtasks /Create /SC DAILY /TN AnvilDaily /ST 18:30 ^
  /TR "C:\path\to\.venv\Scripts\python.exe -m anvil.cli ledger run-daily NIFTY,BANKNIFTY --source upstox"
```

Look-ahead and survivorship are enforced as **failing tests** (`tests/test_backtest_guards.py`):
a backtest cannot peek past an expiry, resolve before settlement, or use a never-traded strike.

## Live data & your brokers

Copy `.env.example` → `.env` (gitignored) and fill in keys, then authenticate:

```bash
anvil auth upstox     # OAuth: opens login, captures the code, caches the daily token
anvil auth groww      # api_key + secret (or TOTP seed)
anvil auth kite        # api_key + request_token  → positions for the risk book
anvil auth status      # token validity per broker
ANVIL_PRIMARY_SOURCE=upstox anvil pull NIFTY            # live chain; real futures forward
```

Upstox covers **NSE and BSE** indices (NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/SENSEX/BANKEX). When a
source doesn't supply a futures price, Anvil recovers the real forward from **put-call parity** at
the ATM strike (tagged `put_call_parity`) — Greeks are never priced off a cost-of-carry guess.

## Hard rails (enforced, not aspirational)

- Greeks are Black-76 on the futures price; live forwards are real (future settle or parity).
- Forecasts are probabilities + a Calibration Score — never accuracy/return claims.
- The reliability curve excludes synthetic/seed/demo data **by default** (`tests/test_source_separation.py`).
- Backtester look-ahead/survivorship guards are failing tests.
- The analyst is grounded (numbers only from the engine); execution is **gated/dry-run by default**
  (`TRADING_AUTOMATION=false`).

See [docs/PITCH.md](docs/PITCH.md) for the product narrative and demo script, and
[docs/decisions/](docs/decisions/) for the architecture decisions.
