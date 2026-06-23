# Deploying Anvil (private, always-on, multi-device)

Anvil ships as one Docker image (built SPA + FastAPI) fronted by Caddy (auto-HTTPS) and backed
by Postgres. It is **not** a public consumer website — it's your private instance behind the
app login, reachable from any device's browser (installable as a PWA).

## What runs
- **anvil** — the API + built React PWA (uvicorn on :8000, internal).
- **postgres** — users, sessions, watchlists, alerts, portfolio snapshots, live-forecast mirror.
- **caddy** — TLS termination + reverse proxy on :80/:443. The DuckDB/Parquet calibration moat
  lives on the `anvil_data` volume; Postgres on `pgdata`.

## 1. One-time setup
```bash
cp .env.example .env
# Edit .env:
#   ANVIL_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
#   POSTGRES_PASSWORD=<strong password>
#   ANVIL_DOMAIN=anvil.<yourname>.duckdns.org   # a free domain pointed at this host's IP
#   ANVIL_PRIMARY_SOURCE=upstox                  # (or leave demo); add UPSTOX_* keys for live data
docker compose up -d --build
```
On first load, open `https://<ANVIL_DOMAIN>/`, create the **owner** account (registration then
closes), complete onboarding, and connect Upstox from the broker panel.

## 2. Oracle Cloud Always Free (recommended)
1. Create an **Always Free Ampere A1 (arm64)** VM (Ubuntu). aarch64 wheels exist for
   numpy/scipy/duckdb/asyncpg; the build works on arm64.
2. In the VCN security list, open ingress **80** and **443**.
3. Install Docker + compose plugin, `git clone` this repo, then the steps in §1.
4. Point a free domain (DuckDNS/Cloudflare) at the VM's public IP so Caddy can issue a cert.

## 3. Render (x86 alternative)
- Create a **Web Service** from this repo (Docker). Render terminates TLS, so you can skip Caddy:
  run only the app, set `ANVIL_DATABASE_URL` to a **Render Postgres** add-on's URL (use the
  `postgresql+asyncpg://` scheme), and set `ANVIL_SECRET_KEY`. Health check path: `/health`.

## 4. Daily cycle (the moat clock)
Schedule the daily record+resolve+snapshot once after the cash close (host cron / Task Scheduler):
```bash
docker compose exec anvil python -m anvil.cli ledger run-daily NIFTY,BANKNIFTY --realized ...
# or hit the owner endpoint:  POST /api/daily/run
```

## 5. Backups
```bash
# Postgres
docker compose exec postgres pg_dump -U anvil anvil > backup_$(date +%F).sql
# DuckDB moat + parquet (run after the daily cycle, when files aren't being written)
docker compose exec anvil tar czf - /app/anvil_data > anvil_data_$(date +%F).tgz
```

## 6. Health & monitoring
`GET /health` returns source + flags; point an uptime monitor (e.g. UptimeRobot, free) at
`https://<ANVIL_DOMAIN>/health`. Logs: `docker compose logs -f anvil`.

## Launch gates (see docs/PHASE1_BACKLOG.md → M9)
Real broker data validated · broker-Greeks fixture activated · public calibration excludes
synthetic · market-data redistribution rights checked · SEBI counsel before accuracy copy ships.
