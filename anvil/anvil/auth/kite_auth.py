"""Zerodha Kite Connect login — request_token → SHA-256 checksum → access_token.

Flow: send the user to the Kite login URL with api_key → on success the redirect carries a
``request_token`` → POST it with ``checksum = SHA256(api_key + request_token + api_secret)`` to
/session/token for a daily access token. Kite is positions-only in Anvil; never wire orders here.

Docs: kite.trade/docs/connect/v3
"""

from __future__ import annotations

import hashlib

import httpx

from ..config import SETTINGS
from .token_store import TokenStore

_LOGIN = "https://kite.zerodha.com/connect/login"
_SESSION = "https://api.kite.trade/session/token"


def login_url(api_key: str) -> str:
    return f"{_LOGIN}?v=3&api_key={api_key}"


def checksum(api_key: str, request_token: str, api_secret: str) -> str:
    return hashlib.sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()


def exchange_request_token(api_key: str, api_secret: str, request_token: str, timeout: float = 15.0) -> dict:
    r = httpx.post(
        _SESSION,
        headers={"X-Kite-Version": "3"},
        data={"api_key": api_key, "request_token": request_token, "checksum": checksum(api_key, request_token, api_secret)},
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("data", {})  # contains access_token, user_id, ...


def login(request_token: str, store: TokenStore | None = None) -> str:
    if not (SETTINGS.kite_api_key and SETTINGS.kite_api_secret):
        raise ValueError("Set KITE_API_KEY and KITE_API_SECRET to log in to Kite.")
    store = store or TokenStore()
    data = exchange_request_token(SETTINGS.kite_api_key, SETTINGS.kite_api_secret, request_token)
    token = data["access_token"]
    store.save("kite", token, user_id=data.get("user_id"))
    return token
