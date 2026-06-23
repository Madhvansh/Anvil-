"""Dhan connector — FALLBACK chain source (OI + IV + Greeks via REST).

Dhan v2 Option Chain is REST POST only and rate-limited to ~1 request / 3 seconds.
Requires DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN. Data API access is gated (free only with
25+ trades / 30 days, else paid).

Docs: https://dhanhq.co/docs/v2/option-chain
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from ..config import SETTINGS, lot_size
from ..models import ChainRow, Greeks, OptionChain, OptionType
from .base import Connector

_BASE = "https://api.dhan.co/v2"

# Underlying security ids (verify against Dhan instrument master).
_SECURITY = {
    "NIFTY": (13, "IDX_I"),
    "BANKNIFTY": (25, "IDX_I"),
    "FINNIFTY": (27, "IDX_I"),
}


class DhanConnector(Connector):
    name = "dhan"
    provides_chain = True
    _MIN_INTERVAL = 3.1  # seconds between calls

    def __init__(self, client_id: str, access_token: str, timeout: float = 10.0):
        if not (client_id and access_token):
            raise ValueError("DhanConnector requires DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN.")
        self._client = httpx.Client(
            timeout=timeout,
            headers={
                "client-id": client_id,
                "access-token": access_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self._last_call = 0.0

    @classmethod
    def from_env(cls) -> "DhanConnector":
        return cls(SETTINGS.dhan_client_id or "", SETTINGS.dhan_access_token or "")

    def _throttle(self) -> None:
        wait = self._MIN_INTERVAL - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _security(self, underlying: str):
        u = underlying.upper()
        if u not in _SECURITY:
            raise ValueError(f"No Dhan security id mapped for {u!r}.")
        return _SECURITY[u]

    def get_expiries(self, underlying: str) -> list[str]:
        sid, seg = self._security(underlying)
        self._throttle()
        r = self._client.post(
            f"{_BASE}/optionchain/expirylist",
            json={"UnderlyingScrip": sid, "UnderlyingSeg": seg},
        )
        r.raise_for_status()
        return sorted(r.json().get("data", []))

    def get_chain(self, underlying: str, expiry: str | None = None) -> OptionChain:
        sid, seg = self._security(underlying)
        if expiry is None:
            exps = self.get_expiries(underlying)
            expiry = exps[0] if exps else None
        self._throttle()
        r = self._client.post(
            f"{_BASE}/optionchain",
            json={"UnderlyingScrip": sid, "UnderlyingSeg": seg, "Expiry": expiry},
        )
        r.raise_for_status()
        data = r.json().get("data", {})
        return self._parse_chain(underlying, expiry, data)

    def _parse_chain(self, underlying: str, expiry: str, data: dict) -> OptionChain:
        spot = float(data.get("last_price") or 0.0)
        oc = data.get("oc") or {}
        rows: list[ChainRow] = []
        for strike_str, node in oc.items():
            strike = float(strike_str)
            for side, ot in (("ce", OptionType.CALL), ("pe", OptionType.PUT)):
                opt = node.get(side) or {}
                if not opt:
                    continue
                g = opt.get("greeks") or {}
                greeks = (
                    Greeks(
                        delta=float(g.get("delta") or 0.0),
                        gamma=float(g.get("gamma") or 0.0),
                        theta=float(g.get("theta") or 0.0),
                        vega=float(g.get("vega") or 0.0),
                        rho=0.0,
                    )
                    if g
                    else None
                )
                iv = opt.get("implied_volatility")
                rows.append(
                    ChainRow(
                        strike=strike,
                        option_type=ot,
                        ltp=opt.get("last_price"),
                        oi=float(opt.get("oi") or 0.0),
                        oi_change=float(opt.get("oi") or 0.0) - float(opt.get("previous_oi") or opt.get("oi") or 0.0),
                        volume=float(opt.get("volume") or 0.0),
                        iv=(float(iv) / 100.0 if iv else None),
                        greeks=greeks,
                    )
                )
        return OptionChain(
            underlying=underlying.upper(),
            spot=spot,
            expiry=expiry,
            timestamp=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            lot_size=lot_size(underlying),
        )

    def close(self) -> None:
        self._client.close()
