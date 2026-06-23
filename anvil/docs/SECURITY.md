# Security posture

Anvil is a private, single-owner (multi-user-ready) instance behind its own login.

## Authentication & sessions
- Passwords hashed with **argon2id** (`auth/passwords.py`).
- **Server-side sessions** (`sessions` table): the cookie carries only an opaque random id
  (`secrets.token_urlsafe(32)`); it is `httponly`, `samesite=lax`, and `secure` on HTTPS. Sessions
  are revocable (logout / expiry) — no long-lived JWT in the browser.
- **Owner bootstrap**: the first registration becomes the owner, then registration closes
  (`/auth/register` 403s thereafter), so a public URL can't accrue accounts.

## Secrets at rest
- Broker tokens are **Fernet-encrypted** (`auth/crypto.py`, key derived from `ANVIL_SECRET_KEY`).
  The store **refuses to persist a token if no key is set** rather than writing plaintext.
- `.env` is gitignored; no secrets are committed. The request logger logs metadata only
  (method/path/status/latency/request-id) — never bodies, tokens, or passwords.

## Data access
- All DB access goes through SQLAlchemy ORM with bound parameters — no string-built SQL.
- Every user-scoped row carries `user_id`; user-scoped endpoints require `current_user`.
- Market analytics are public **within the instance** (same data for everyone, not user data);
  the instance itself is private behind the deploy gate.

## Transport & CORS
- Caddy terminates TLS (auto Let's Encrypt). The SPA is served same-origin, so cookies need no
  cross-origin exposure; `CORSMiddleware` is enabled **only** when `ANVIL_DEV=1` (Vite dev server).

## Trading safety
- `TRADING_AUTOMATION=false` (auto-execution gated off); assisted execution is dry-run by default.
- The copilot passes every answer through the compliance guardrail (`agent/guardrail.py`): no
  buy/sell/target/guarantee language; deterministic narrator fallback.

## Before launch (gates)
- [ ] Real broker data validated (Upstox live pull) and **broker-Greeks fixture activated**
      (`python -m anvil.ingest.capture NIFTY` → `tests/test_broker_validation.py` passes).
- [ ] Public calibration excludes synthetic (enforced by `PUBLIC_CLASSES` + `test_source_separation.py`).
- [ ] Market-data redistribution rights checked (Upstox/NSE ToS).
- [ ] SEBI counsel before any accuracy marketing ships.
- [ ] Run `/security-review` on the branch; set a strong `ANVIL_SECRET_KEY` + `POSTGRES_PASSWORD`.

## Next hardening (post-demo)
- Rate limiting (a `Cache`/limiter seam exists), optional 2FA, secret rotation runbook,
  per-user broker tokens unified onto the DB store for true multi-tenant.
