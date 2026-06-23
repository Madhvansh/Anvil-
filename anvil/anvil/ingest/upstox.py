"""Upstox connector — PRIMARY market-data source (chain + OI + IV + Greeks).

Upstox v2 option-chain returns, per strike, market_data (ltp/oi/volume/bid/ask) and
option_greeks (iv/delta/gamma/theta/vega) in one call — so it's our default chain feed.
Requires UPSTOX_ACCESS_TOKEN (daily OAuth token). Verify instrument keys against the
live instruments master before production.

Docs: https://upstox.com/developer/api-documentation (get-put-call-option-chain)
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from ..config import SETTINGS
from ..models import Bar, ChainRow, Greeks, OptionChain, OptionType
from ..store.bars import resample_bars
from .base import Connector, attach_parity_forward
from .instruments import get_master

_BASE = "https://api.upstox.com/v2"

# Native Upstox v2 candle intervals; derived timeframes are fetched at 1minute and resampled.
_NATIVE_INTERVAL = {"1m": "1minute", "30m": "30minute", "1d": "day", "1w": "week", "1M": "month"}
_DERIVED_FROM_1M = {"5m", "15m", "1h"}

# Index instrument keys (verify against the live instruments dump).
_INSTRUMENT_KEYS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
    "BANKEX": "BSE_INDEX|BANKEX",
}


class UpstoxConnector(Connector):
    name = "upstox"
    provides_chain = True

    def __init__(self, access_token: str, timeout: float = 10.0):
        if not access_token:
            raise ValueError("UpstoxConnector requires an access token (set UPSTOX_ACCESS_TOKEN).")
        self._token = access_token
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
        )

    @classmethod
    def from_env(cls) -> "UpstoxConnector":
        from ..auth.token_store import TokenStore

        tok = TokenStore().access_token("upstox") or SETTINGS.upstox_access_token
        if not tok:
            raise ValueError("No Upstox token. Run `anvil auth upstox` (or set UPSTOX_ACCESS_TOKEN).")
        return cls(tok)

    def _instrument_key(self, underlying: str) -> str:
        """Underlying instrument key: hard-coded index map first, else the instrument master (equities +
        any index not in the map). Upstox's option/chain + candle endpoints accept BOTH index and equity
        keys, so this is the single resolver for index AND single-stock chains/candles."""
        u = underlying.upper()
        if u in _INSTRUMENT_KEYS:
            return _INSTRUMENT_KEYS[u]
        key = get_master().instrument_key_for(u)
        if not key:
            raise ValueError(
                f"No Upstox instrument key for {u!r}; run `anvil data fetch-instruments` "
                f"(or add an index to _INSTRUMENT_KEYS).")
        return key

    def get_expiries(self, underlying: str) -> list[str]:
        r = self._client.get(
            f"{_BASE}/option/contract", params={"instrument_key": self._instrument_key(underlying)}
        )
        r.raise_for_status()
        data = r.json().get("data", [])
        return sorted({row["expiry"] for row in data if "expiry" in row})

    def get_chain(self, underlying: str, expiry: str | None = None) -> OptionChain:
        if expiry is None:
            exps = self.get_expiries(underlying)
            if not exps:
                raise RuntimeError(f"No expiries returned for {underlying}")
            expiry = exps[0]
        r = self._client.get(
            f"{_BASE}/option/chain",
            params={"instrument_key": self._instrument_key(underlying), "expiry_date": expiry},
        )
        r.raise_for_status()
        payload = r.json().get("data", [])
        return self._parse_chain(underlying, expiry, payload)

    def _parse_chain(self, underlying: str, expiry: str, payload: list) -> OptionChain:
        rows: list[ChainRow] = []
        spot = 0.0
        for node in payload:
            strike = float(node["strike_price"])
            spot = float(node.get("underlying_spot_price") or spot)
            for side, ot in (("call_options", OptionType.CALL), ("put_options", OptionType.PUT)):
                opt = node.get(side) or {}
                md = opt.get("market_data") or {}
                gd = opt.get("option_greeks") or {}
                greeks = None
                if gd:
                    greeks = Greeks(
                        delta=float(gd.get("delta") or 0.0),
                        gamma=float(gd.get("gamma") or 0.0),
                        theta=float(gd.get("theta") or 0.0),
                        vega=float(gd.get("vega") or 0.0),
                        rho=float(gd.get("rho") or 0.0),
                    )
                iv = gd.get("iv")
                rows.append(
                    ChainRow(
                        strike=strike,
                        option_type=ot,
                        ltp=md.get("ltp"),
                        bid=md.get("bid_price"),
                        ask=md.get("ask_price"),
                        oi=float(md.get("oi") or 0.0),
                        oi_change=float(md.get("oi") or 0.0) - float(md.get("prev_oi") or md.get("oi") or 0.0),
                        volume=float(md.get("volume") or 0.0),
                        iv=(float(iv) / 100.0 if iv else None),  # Upstox IV is in %
                        greeks=greeks,
                    )
                )
        ch = OptionChain(
            underlying=underlying.upper(),
            spot=spot,
            expiry=expiry,
            timestamp=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            lot_size=get_master().lot_size(underlying),  # master (real F&O lots) → config fallback
        )
        return attach_parity_forward(ch)

    # --- candles (multi-timeframe momentum substrate) ----------------------- #
    def _resolve_candle_key(self, symbol: str) -> str:
        """Instrument key for a candle fetch — same resolver as chains (index map, else master)."""
        return self._instrument_key(symbol)

    @staticmethod
    def _parse_candles(candles: list, symbol: str, tf: str) -> list[Bar]:
        """Upstox candle arrays → ascending list[Bar]. Each candle = [ts, o, h, l, c, volume, oi]."""
        out: list[Bar] = []
        for c in candles or []:
            if not c or len(c) < 5:
                continue
            out.append(Bar(
                symbol=symbol.upper(), tf=tf, ts=str(c[0]),
                open=float(c[1]), high=float(c[2]), low=float(c[3]), close=float(c[4]),
                volume=float(c[5]) if len(c) > 5 and c[5] is not None else 0.0,
                oi=(float(c[6]) if len(c) > 6 and c[6] is not None else None),
            ))
        out.sort(key=lambda b: b.ts)  # Upstox returns newest-first; momentum wants oldest→newest
        return out

    def get_candles(
        self, symbol: str, tf: str = "1d", *, from_date: str | None = None,
        to_date: str | None = None, intraday: bool = False,
    ) -> list[Bar]:
        """Historical/intraday OHLCV bars for an index OR single stock at timeframe ``tf``
        (1m/5m/15m/30m/1h/1d/1w). Derived timeframes (5m/15m/1h) are fetched at 1minute and resampled."""
        key = self._resolve_candle_key(symbol)
        derived = tf in _DERIVED_FROM_1M
        native_tf = "1m" if derived else tf
        interval = _NATIVE_INTERVAL.get(native_tf)
        if interval is None:
            raise ValueError(f"Unsupported timeframe {tf!r} (supported: {sorted(_NATIVE_INTERVAL) + sorted(_DERIVED_FROM_1M)})")
        if intraday:
            url = f"{_BASE}/historical-candle/intraday/{key}/{interval}"
        else:
            to_d = to_date or ""
            from_d = from_date or ""
            url = f"{_BASE}/historical-candle/{key}/{interval}/{to_d}/{from_d}".rstrip("/")
        r = self._client.get(url)
        r.raise_for_status()
        candles = (r.json().get("data") or {}).get("candles") or []
        bars = self._parse_candles(candles, symbol, native_tf)
        if derived:
            bars = resample_bars(bars, tf)
        return bars

    def get_historical_candles(
        self, underlying: str, interval_min: int = 15, start: str | None = None, end: str | None = None
    ) -> list[tuple[str, float, float, float, float]]:
        """Base-contract 5-tuple OHLC (for the real-day replay path). Maps ``interval_min`` → a tf."""
        tf = {1: "1m", 5: "5m", 15: "15m", 30: "30m", 60: "1h"}.get(int(interval_min), "15m")
        bars = self.get_candles(underlying, tf, from_date=start, to_date=end,
                                intraday=(start is None and end is None))
        return [(b.ts, b.open, b.high, b.low, b.close) for b in bars]

    def close(self) -> None:
        self._client.close()
