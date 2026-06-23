"""Zerodha Kite connector — reads the user's POSITIONS only (read-only by design).

Two paths:
  * Kite Connect REST (api_key + access_token) — used here for positions/holdings/OI quotes.
  * Hosted Kite MCP (OAuth) — read-only; we ship an MCP introspection helper so you can
    confirm the exact tools/endpoint before depending on it (plan verification step 6).

The official Kite surface exposes OI on quotes but NO option chain / Greeks / IV — anvil
computes those itself. Never wire order placement here; execution lives behind the gated
order module.

Docs: https://kite.trade/docs/connect/v3/
"""

from __future__ import annotations

import json

import httpx

from ..config import SETTINGS
from ..models import OptionChain, OptionType, Position
from .base import Connector

_BASE = "https://api.kite.trade"


class KiteConnector(Connector):
    name = "kite"
    provides_chain = False
    provides_positions = True

    def __init__(self, api_key: str, access_token: str, timeout: float = 10.0):
        if not (api_key and access_token):
            raise ValueError("KiteConnector requires KITE_API_KEY and KITE_ACCESS_TOKEN.")
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "X-Kite-Version": "3",
                "Authorization": f"token {api_key}:{access_token}",
            },
        )

    @classmethod
    def from_env(cls) -> "KiteConnector":
        from ..auth.token_store import TokenStore

        tok = TokenStore().access_token("kite") or SETTINGS.kite_access_token
        if not (SETTINGS.kite_api_key and tok):
            raise ValueError("No Kite session. Run `anvil auth kite` (needs KITE_API_KEY/KITE_API_SECRET).")
        return cls(SETTINGS.kite_api_key, tok)

    def get_chain(self, underlying: str, expiry: str | None = None) -> OptionChain:
        raise NotImplementedError(
            "Kite has no option-chain endpoint. Use Upstox/Dhan for chains; Kite is positions-only."
        )

    def get_positions(self) -> list[Position]:
        r = self._client.get(f"{_BASE}/portfolio/positions")
        r.raise_for_status()
        net = r.json().get("data", {}).get("net", [])
        return [self._parse_position(p) for p in net if p.get("quantity")]

    def _parse_position(self, p: dict) -> Position:
        sym = p.get("tradingsymbol", "")
        instrument_type = "EQ"
        option_type = None
        if sym.endswith("CE"):
            instrument_type, option_type = "CE", OptionType.CALL
        elif sym.endswith("PE"):
            instrument_type, option_type = "PE", OptionType.PUT
        elif "FUT" in sym:
            instrument_type = "FUT"
        return Position(
            symbol=sym,
            underlying=p.get("name") or sym,
            instrument_type=instrument_type,
            option_type=option_type,
            quantity=float(p.get("quantity") or 0.0),
            avg_price=float(p.get("average_price") or 0.0),
            ltp=float(p.get("last_price") or 0.0),
        )

    def close(self) -> None:
        self._client.close()


def introspect_mcp(url: str | None = None, access_token: str | None = None, timeout: float = 15.0) -> dict:
    """Best-effort MCP ``tools/list`` against a hosted MCP endpoint.

    Returns the raw JSON-RPC response (or an error dict). Hosted Kite/Groww MCPs require
    an OAuth bearer token; without one this typically returns 401 — that's expected, and
    confirms the endpoint is live. Run this manually to verify the exact tool set/host
    before wiring any MCP tool (Kite docs reference both mcp.kite.trade and
    kite-mcp-server.fly.dev — confirm which your account uses).
    """
    url = url or SETTINGS.kite_mcp_url
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    try:
        with httpx.Client(timeout=timeout, headers=headers) as c:
            r = c.post(url, content=json.dumps(body))
            ctype = r.headers.get("content-type", "")
            try:
                parsed = r.json()
            except Exception:
                parsed = {"raw": r.text[:2000]}
            return {"status": r.status_code, "content_type": ctype, "response": parsed}
    except httpx.HTTPError as e:
        return {"error": str(e), "url": url}
