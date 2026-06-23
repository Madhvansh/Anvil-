"""Groww connector — data fallback (chain+OI+Greeks) and the execution broker.

Uses the official ``growwapi`` SDK (lazy-imported so the core/tests run without it; the SDK
targets Python ≤3.13, so run the Groww path in the 3.12 Docker image). Auth prefers the
non-expiring TOTP flow when a seed is set, else the daily-approval secret flow.

Docs: groww.in/trade-api/docs/python-sdk
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..config import SETTINGS, lot_size
from ..models import ChainRow, Greeks, OptionChain, OptionType, Position
from .base import Connector, attach_parity_forward

try:
    from zoneinfo import ZoneInfo

    _IST = ZoneInfo("Asia/Kolkata")
except Exception:  # pragma: no cover
    _IST = timezone(timedelta(hours=5, minutes=30))

# Index -> (Groww trading_symbol, exchange attr) for intraday candles (SEGMENT_CASH). NIFTY is
# verified against the live API; the others are best-effort and degrade to a clear error if empty.
_GROWW_INDEX_CANDLE = {
    "NIFTY": ("NIFTY", "EXCHANGE_NSE"),
    "BANKNIFTY": ("BANKNIFTY", "EXCHANGE_NSE"),
    "FINNIFTY": ("FINNIFTY", "EXCHANGE_NSE"),
    "MIDCPNIFTY": ("MIDCPNIFTY", "EXCHANGE_NSE"),
    "SENSEX": ("SENSEX", "EXCHANGE_BSE"),
    "BANKEX": ("BANKEX", "EXCHANGE_BSE"),
}


def _make_client():
    """Authenticate and return a GrowwAPI client (raises a clear error if SDK/creds missing).

    Prefers a pre-generated access token (Groww dashboard-issued, or pasted via the app's
    Connect → Groww, or GROWW_ACCESS_TOKEN) used directly; otherwise generates one from
    GROWW_API_KEY + (TOTP seed or secret)."""
    try:
        from growwapi import GrowwAPI
    except ImportError as e:  # pragma: no cover - optional dep
        raise RuntimeError(
            "growwapi not installed (the SDK targets Python <=3.13). Run the Groww path in the "
            "Python 3.12 Docker image, or `pip install \".[brokers]\"` on a <=3.13 interpreter."
        ) from e

    # 1) Pre-generated token (no key/secret needed).
    token = SETTINGS.groww_access_token
    if not token:
        from ..auth.token_store import TokenStore

        token = TokenStore().access_token("groww")
    if token:
        return GrowwAPI(token)

    # 2) Generate one from key + TOTP/secret.
    if SETTINGS.groww_totp_seed and SETTINGS.groww_api_key:
        import pyotp

        totp = pyotp.TOTP(SETTINGS.groww_totp_seed).now()
        token = GrowwAPI.get_access_token(api_key=SETTINGS.groww_api_key, totp=totp)
    elif SETTINGS.groww_api_key and SETTINGS.groww_api_secret:
        token = GrowwAPI.get_access_token(api_key=SETTINGS.groww_api_key, secret=SETTINGS.groww_api_secret)
    else:
        raise RuntimeError("Connect Groww (paste a token) or set GROWW_API_KEY + (GROWW_TOTP_SEED or GROWW_API_SECRET).")
    return GrowwAPI(token)


def _g(d: dict, *names, default=None):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default


class GrowwConnector(Connector):
    name = "groww"
    provides_chain = True
    provides_positions = True

    def __init__(self, client=None):
        self.groww = client or _make_client()

    @classmethod
    def from_env(cls) -> "GrowwConnector":
        return cls()

    def get_expiries(self, underlying: str) -> list[str]:
        """FUTURE expiries (ISO YYYY-MM-DD), nearest first. Groww returns the whole calendar
        including PAST expiries (whose chains are empty), so drop anything before today — ISO
        date strings compare lexicographically, so a plain string compare is a date compare."""
        g = self.groww
        raw = g.get_expiries(exchange=g.EXCHANGE_NSE, underlying_symbol=underlying.upper())
        items = _g(raw, "expiries", "expiry_dates", "data", default=raw if isinstance(raw, list) else []) or []
        out: list[str] = []
        for e in items:
            s = e if isinstance(e, str) else _g(e, "expiry", "expiry_date", "date", default="")
            if s:
                out.append(s)
        today = datetime.now(timezone.utc).date().isoformat()
        future = sorted(s for s in out if s >= today)
        return future or sorted(out)

    def _parse_strikes(self, raw: dict) -> list[ChainRow]:
        """Groww's option chain is ``{"underlying_ltp": .., "strikes": {"<strike>": {"CE": {..},
        "PE": {..}}}}`` where each leg carries ``ltp``/``open_interest``/``volume`` and a nested
        ``greeks`` dict (delta/gamma/theta/vega/rho/iv). Older/list shapes are tolerated too."""
        rows: list[ChainRow] = []
        strikes = raw.get("strikes")
        if isinstance(strikes, dict):
            nodes = [(_g(v, "strike_price", "strike", default=k), v) for k, v in strikes.items()]
            sides = (("CE", OptionType.CALL), ("PE", OptionType.PUT))
        else:
            chain_rows = _g(raw, "option_chain", "rows", "data", default=[]) or []
            nodes = [(_g(n, "strike_price", "strike", default=0.0), n) for n in chain_rows]
            sides = (("call", OptionType.CALL), ("put", OptionType.PUT))
        for strike_key, node in nodes:
            try:
                strike = float(strike_key)
            except (TypeError, ValueError):
                continue
            for side, ot in sides:
                leg = _g(node, side, side + "_options", default=None)
                row = self._row_from_leg(strike, ot, leg)
                if row is not None:
                    rows.append(row)
        return rows

    @staticmethod
    def _row_from_leg(strike: float, ot: OptionType, leg) -> ChainRow | None:
        if not leg:
            return None
        gd = _g(leg, "greeks", default=None) or {}
        greek_src = gd or leg  # nested ``greeks`` (real Groww) or flat keys on the leg (alt shape)
        iv = _g(gd, "iv", default=None)
        if iv is None:
            iv = _g(leg, "iv", "implied_volatility", default=None)  # fallback if not nested
        greeks = None
        if any(k in greek_src for k in ("delta", "gamma", "theta", "vega")):
            greeks = Greeks(
                delta=float(_g(greek_src, "delta", default=0.0) or 0.0),
                gamma=float(_g(greek_src, "gamma", default=0.0) or 0.0),
                theta=float(_g(greek_src, "theta", default=0.0) or 0.0),
                vega=float(_g(greek_src, "vega", default=0.0) or 0.0),
                rho=float(_g(greek_src, "rho", default=0.0) or 0.0),
            )
        ivf = None
        if iv not in (None, ""):
            ivf = float(iv)
            ivf = ivf / 100.0 if ivf > 3 else ivf  # Groww quotes IV in %
        return ChainRow(
            strike=strike, option_type=ot,
            ltp=_g(leg, "ltp", "last_price", default=None),
            oi=float(_g(leg, "open_interest", "oi", default=0.0) or 0.0),
            oi_change=float(_g(leg, "oi_day_change", "oi_change", default=0.0) or 0.0),
            volume=float(_g(leg, "volume", default=0.0) or 0.0),
            iv=ivf,
            greeks=greeks,
        )

    def get_chain(self, underlying: str, expiry: str | None = None) -> OptionChain:
        g = self.groww
        # Groww needs an explicit expiry (ISO YYYY-MM-DD). When none is given, try the nearest few
        # FUTURE expiries and use the first that actually returns a populated chain (the very
        # nearest can be empty right around expiry day).
        candidates = [expiry] if expiry else self.get_expiries(underlying)[:6]
        if not candidates:
            raise RuntimeError(f"No expiries returned by Groww for {underlying}")
        raw = None
        used = None
        last_exc: Exception | None = None
        for exp in candidates:
            try:
                r = g.get_option_chain(exchange=g.EXCHANGE_NSE, underlying=underlying.upper(), expiry_date=exp)
            except Exception as e:  # noqa: BLE001 - try the next candidate expiry
                last_exc = e
                continue
            if (r.get("strikes") if isinstance(r, dict) else None) or _g(r, "option_chain", "rows", "data", default=None):
                raw, used = r, exp
                break
        if raw is None:
            if last_exc is not None:
                raise last_exc
            raise RuntimeError(f"Groww returned an empty option chain for {underlying} (tried {candidates}).")
        spot = float(_g(raw, "underlying_ltp", "spot", "underlying_spot_price", default=0.0))
        ch = OptionChain(
            underlying=underlying.upper(), spot=spot, expiry=used or "",
            timestamp=datetime.now(timezone.utc).isoformat(),
            rows=self._parse_strikes(raw), lot_size=lot_size(underlying),
        )
        return attach_parity_forward(ch)

    def get_historical_candles(
        self, underlying: str, interval_min: int = 15, start: str | None = None, end: str | None = None
    ) -> list[tuple[str, float, float, float, float]]:
        """Real intraday OHLC for the INDEX (SEGMENT_CASH). Returns [(iso_ts_ist, o, h, l, c), ...]
        nearest-first. Defaults to today's IST session (09:15->15:30). Used to replay the REAL day."""
        g = self.groww
        sym, exch_attr = _GROWW_INDEX_CANDLE.get(underlying.upper(), (underlying.upper(), "EXCHANGE_NSE"))
        if not (start and end):
            day = datetime.now(_IST).date().isoformat()
            start = start or f"{day} 09:15:00"
            end = end or f"{day} 15:30:00"
        raw = g.get_historical_candle_data(
            trading_symbol=sym, exchange=getattr(g, exch_attr), segment=g.SEGMENT_CASH,
            start_time=start, end_time=end, interval_in_minutes=int(interval_min),
        )
        candles = (raw.get("candles") if isinstance(raw, dict) else raw) or []
        out: list[tuple[str, float, float, float, float]] = []
        for c in candles:
            if not c or len(c) < 5:
                continue
            ts = datetime.fromtimestamp(int(c[0]), tz=_IST).isoformat()
            out.append((ts, float(c[1]), float(c[2]), float(c[3]), float(c[4])))
        return out

    def get_positions(self) -> list[Position]:
        g = self.groww
        data = g.get_positions_for_user()
        positions = _g(data, "positions", default=data) if isinstance(data, dict) else data
        out: list[Position] = []
        for p in positions or []:
            sym = _g(p, "trading_symbol", "symbol", default="")
            instrument_type = "CE" if sym.endswith("CE") else "PE" if sym.endswith("PE") else "EQ"
            qty = float(_g(p, "net_carry_forward_quantity", "quantity", "net_quantity", default=0.0))
            if not qty:
                continue
            out.append(
                Position(
                    symbol=sym, underlying=_g(p, "underlying", default=sym), instrument_type=instrument_type,
                    option_type=OptionType.CALL if instrument_type == "CE" else OptionType.PUT if instrument_type == "PE" else None,
                    quantity=qty, avg_price=float(_g(p, "net_price", "average_price", default=0.0)),
                    ltp=float(_g(p, "ltp", "last_price", default=0.0)),
                )
            )
        return out
