"""Broker connection endpoints (gated). Stores the per-user token encrypted in the DB and
mirrors the owner's token to the file TokenStore so the sync data connectors pick it up.

Upstox OAuth is interactive (browser redirect); /auth-url returns the dialog URL for the
SPA to open. For the owner demo, a token can also be connected directly via /connect."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth import broker_store, crypto
from ...auth.deps import current_user, current_user_optional
from ...config import SETTINGS
from ...db.engine import get_session
from ...db.models import User
from ...obs import log

router = APIRouter(prefix="/api/broker", tags=["broker"])


async def _store_token(session: AsyncSession, user: User, broker: str, token: str, expires_at=None, meta=None):
    """Persist a broker token: encrypted per-user in the DB + mirrored to the file store (owner)
    so the sync connectors pick it up immediately."""
    if crypto.encryption_available():
        await broker_store.save_token(
            session, user_id=user.id, broker=broker, access_token=token, expires_at=expires_at, meta=meta
        )
    if user.role == "owner":
        from ...auth.token_store import TokenStore

        TokenStore().save(broker, token, expires_at=expires_at)
    # A freshly connected broker must take effect on the NEXT analytics request, not after the
    # ~45s analyze-cache TTL. Drop the cache so a stale demo (or other-source) payload can't linger
    # and keep the UI on "demo" right after the user goes live.
    from ..cache import ANALYZE_CACHE

    ANALYZE_CACHE.clear()

_SUPPORTED = {"upstox", "dhan", "groww", "kite"}


class ConnectIn(BaseModel):
    access_token: str
    expires_at: str | None = None  # ISO; defaults to broker-correct expiry for upstox/kite
    meta: dict | None = None


@router.get("/connections")
async def connections(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await broker_store.list_connections(session, user.id)


@router.get("/upstox/auth-url")
async def upstox_auth_url(user: User = Depends(current_user)):
    if not SETTINGS.upstox_api_key:
        raise HTTPException(400, "UPSTOX_API_KEY not set on the server.")
    from ...auth.upstox_auth import build_dialog_url

    return {"auth_url": build_dialog_url(SETTINGS.upstox_api_key, SETTINGS.upstox_redirect_uri)}


@router.get("/upstox/callback")
async def upstox_callback(
    code: str | None = None,
    state: str | None = None,
    user: User | None = Depends(current_user_optional),
    session: AsyncSession = Depends(get_session),
):
    """Upstox OAuth redirect target: exchange the code for an access token, store it, and bounce
    back into the app. The browser carries the session cookie (SameSite=Lax top-level GET), so we
    know which user to attach the token to."""
    if user is None:
        # Session cookie didn't ride the redirect (signed out, or cookie blocked). The UI shows a
        # "sign in then reconnect" message rather than silently doing nothing.
        log.warning("upstox_callback_no_session")
        return RedirectResponse(url="/?broker=upstox_session_lost", status_code=303)
    if not code:
        return RedirectResponse(url="/?broker=upstox_error", status_code=303)
    if not (SETTINGS.upstox_api_key and SETTINGS.upstox_api_secret):
        return RedirectResponse(url="/?broker=upstox_unconfigured", status_code=303)
    from ...auth.upstox_auth import exchange_code

    try:
        resp = exchange_code(code, SETTINGS.upstox_api_key, SETTINGS.upstox_api_secret, SETTINGS.upstox_redirect_uri)
        token = resp["access_token"]
    except Exception as e:  # noqa: BLE001 - surface a clean message to the UI, don't 500 the redirect
        # Log the REAL reason server-side (status + body) — this is what was invisible before.
        detail = _exchange_error_detail(e)
        log.warning("upstox_exchange_failed", error=type(e).__name__, detail=detail,
                    redirect_uri=SETTINGS.upstox_redirect_uri)
        return RedirectResponse(url="/?broker=upstox_exchange_failed", status_code=303)
    await _store_token(session, user, "upstox", token, meta={"via": "oauth"})
    log.info("upstox_connected", user_id=user.id)
    return RedirectResponse(url="/?broker=upstox_connected", status_code=303)


def _exchange_error_detail(e: Exception) -> str:
    """Best-effort short detail for an Upstox token-exchange failure (HTTP status + body)."""
    import httpx

    if isinstance(e, httpx.HTTPStatusError):
        body = ""
        try:
            body = e.response.text[:300]
        except Exception:  # noqa: BLE001
            body = ""
        return f"HTTP {e.response.status_code}: {body}"
    return str(e) or type(e).__name__


class ExchangeIn(BaseModel):
    code: str


@router.post("/upstox/exchange")
async def upstox_exchange(
    body: ExchangeIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    """SPA-side OAuth completion: the app posts the ?code it received (used when a stale service
    worker served the app shell for the callback instead of letting it reach /upstox/callback)."""
    if not (SETTINGS.upstox_api_key and SETTINGS.upstox_api_secret):
        raise HTTPException(400, "UPSTOX_API_KEY / UPSTOX_API_SECRET not set on the server.")
    from ...auth.upstox_auth import exchange_code

    try:
        resp = exchange_code(body.code, SETTINGS.upstox_api_key, SETTINGS.upstox_api_secret, SETTINGS.upstox_redirect_uri)
        token = resp["access_token"]
    except Exception as e:  # noqa: BLE001 - surface the broker error to the UI
        detail = _exchange_error_detail(e)
        log.warning("upstox_exchange_failed", error=type(e).__name__, detail=detail,
                    redirect_uri=SETTINGS.upstox_redirect_uri)
        raise HTTPException(
            400,
            f"Upstox token exchange failed ({detail}). Verify UPSTOX_API_SECRET and that the "
            f"redirect URI registered in your Upstox app exactly matches {SETTINGS.upstox_redirect_uri}.",
        ) from e
    await _store_token(session, user, "upstox", token, meta={"via": "oauth"})
    log.info("upstox_connected", user_id=user.id)
    return {"broker": "upstox", "connected": True}


@router.post("/{broker}/connect")
async def connect(
    broker: str,
    body: ConnectIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    broker = broker.lower()
    if broker not in _SUPPORTED:
        raise HTTPException(400, f"Unsupported broker {broker!r}")
    if not crypto.encryption_available():
        raise HTTPException(500, "ANVIL_SECRET_KEY not set — cannot store broker tokens securely.")

    expires_at = None
    if body.expires_at:
        try:
            expires_at = datetime.fromisoformat(body.expires_at)
        except ValueError:
            raise HTTPException(400, "expires_at must be ISO-8601") from None

    await _store_token(session, user, broker, body.access_token, expires_at=expires_at, meta=body.meta)
    return {"broker": broker, "connected": True}
