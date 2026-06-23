# Multi-stage build: compile the React/Vite PWA, then run it from the pinned Python image.
# Python is pinned to 3.12 (some broker SDKs / quant wheels lag the host's 3.14). See
# docs/decisions/0003-python-3.12-docker-pin.md

# ---- Stage 1: build the SPA ----
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Emit to an absolute path we can copy from in the runtime stage.
RUN npm run build -- --outDir /spa --emptyOutDir

# ---- Stage 2: Python runtime ----
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first (better layer caching). app+prod add the OLTP spine (Postgres/asyncpg,
# alembic, argon2, cryptography). brokers (growwapi/pyotp/kiteconnect) is INCLUDED here so the
# 3.12 image can serve live Groww/Kite data — the local 3.14 dev server can't (the SDKs cap at
# Python <=3.13). Upstox uses httpx and needs no SDK.
COPY pyproject.toml ./
COPY anvil ./anvil
RUN pip install --upgrade pip && pip install ".[dev,app,prod,brokers,crosscheck,copilot,schedule]"

# App source + the built SPA from stage 1.
COPY . .
COPY --from=web /spa ./anvil/api/static

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/anvil_data && chown -R appuser /app
USER appuser

EXPOSE 8000

# Apply DB migrations (Postgres in prod; harmless on sqlite) then serve. `&&` fails the
# container loudly if migrations fail rather than booting with no tables. --proxy-headers lets
# uvicorn trust Caddy's X-Forwarded-Proto so session cookies get the Secure flag behind TLS.
CMD ["sh", "-c", "alembic upgrade head && uvicorn anvil.api.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
