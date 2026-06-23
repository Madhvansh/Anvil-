"""Upstox OAuth2 (authorization_code) — daily interactive login, no refresh token.

Flow: send the user to the dialog URL → they log in → Upstox redirects to the registered
redirect_uri with a single-use ``code`` → exchange it (form-urlencoded) for an access token
that expires at 03:30 IST next day. We capture the code via a one-shot loopback listener with
a manual-paste fallback, then persist via TokenStore.

Docs: upstox.com/developer/api-documentation/get-token
"""

from __future__ import annotations

import http.server
import queue
import threading
import urllib.parse
import webbrowser

import httpx

from ..config import SETTINGS
from .token_store import TokenStore

_DIALOG = "https://api.upstox.com/v2/login/authorization/dialog"
_TOKEN = "https://api.upstox.com/v2/login/authorization/token"


def build_dialog_url(client_id: str, redirect_uri: str, state: str = "anvil") -> str:
    q = urllib.parse.urlencode(
        {"response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "state": state}
    )
    return f"{_DIALOG}?{q}"


def capture_code(dialog_url: str, redirect_uri: str, expected_state: str = "anvil", timeout: int = 180) -> str:
    """Open the browser; capture ``code`` via a one-shot loopback server, else manual paste."""
    pr = urllib.parse.urlparse(redirect_uri)
    host, port, path = pr.hostname, pr.port, pr.path or "/"
    result: queue.Queue = queue.Queue(maxsize=1)

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != path:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Anvil: auth received. You may close this tab.")
            result.put(urllib.parse.parse_qs(parsed.query))

        def log_message(self, *a):  # silence
            return

    try:
        srv = http.server.HTTPServer((host, port), Handler)
        threading.Thread(target=srv.handle_request, daemon=True).start()
        webbrowser.open(dialog_url)
        try:
            qs = result.get(timeout=timeout)
        finally:
            srv.server_close()
    except Exception:  # headless / port blocked → manual paste
        print("Open this URL, log in, then paste the FULL redirected URL:")
        print(dialog_url)
        pasted = input("redirected URL> ").strip()
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)

    if qs.get("state", [None])[0] != expected_state:
        raise ValueError("OAuth state mismatch (possible CSRF)")
    code = qs.get("code", [None])[0]
    if not code:
        raise ValueError("No authorization code returned")
    return code


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str, timeout: float = 15.0) -> dict:
    r = httpx.post(
        _TOKEN,
        headers={"accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()  # contains access_token (+ profile); NO refresh_token


def login(store: TokenStore | None = None) -> str:
    """Run the full interactive login and persist the token. Returns the access token."""
    if not (SETTINGS.upstox_api_key and SETTINGS.upstox_api_secret):
        raise ValueError("Set UPSTOX_API_KEY and UPSTOX_API_SECRET to log in to Upstox.")
    store = store or TokenStore()
    url = build_dialog_url(SETTINGS.upstox_api_key, SETTINGS.upstox_redirect_uri)
    code = capture_code(url, SETTINGS.upstox_redirect_uri)
    resp = exchange_code(code, SETTINGS.upstox_api_key, SETTINGS.upstox_api_secret, SETTINGS.upstox_redirect_uri)
    token = resp["access_token"]
    store.save("upstox", token, user_id=resp.get("user_id"), email=resp.get("email"))
    return token


def ensure_token(store: TokenStore | None = None) -> str:
    """Return a valid cached token, or run the interactive login. Falls back to env token."""
    store = store or TokenStore()
    if store.is_valid("upstox"):
        return store.access_token("upstox")  # type: ignore[return-value]
    if SETTINGS.upstox_access_token:  # manually-provided token
        store.save("upstox", SETTINGS.upstox_access_token)
        return SETTINGS.upstox_access_token
    return login(store)
