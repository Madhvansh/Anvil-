"""Instrument master — real lot sizes + symbol resolution from broker instrument dumps.

``config.INDEX_LOT_SIZE`` is a documented FALLBACK; live and single-stock F&O lot sizes must come
from the broker's instrument master (Upstox JSON, Kite CSV). Sizing and rupee P&L depend on this,
so the loader is the bridge from the config fallback to correct contract sizes. Offline-safe: with
no dump loaded, ``lot_size`` transparently falls back to config.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import lot_size as config_lot_size

# Upstox publishes a free, unauthenticated complete instrument dump (gzipped JSON).
_UPSTOX_DUMP_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.json.gz"


@dataclass
class InstrumentMaster:
    lot_by_name: dict[str, int] = field(default_factory=dict)
    records: list[dict] = field(default_factory=list)
    # symbol (upper) → broker instrument_key, for spot/cash candle fetches (EQ + INDEX segments).
    key_by_symbol: dict[str, str] = field(default_factory=dict)
    # symbol (upper) → list of option instrument records (Wave 4 single-stock chains).
    options_by_symbol: dict[str, list[dict]] = field(default_factory=dict)

    def lot_size(self, underlying: str, default: int | None = None) -> int:
        """Lot size for an underlying — from the loaded master, else the config fallback."""
        key = underlying.upper()
        if key in self.lot_by_name:
            return self.lot_by_name[key]
        return config_lot_size(key) if default is None else default

    def has(self, underlying: str) -> bool:
        return underlying.upper() in self.lot_by_name

    def instrument_key_for(self, symbol: str) -> str | None:
        """Broker instrument_key for a spot/cash symbol (index or equity); None if not loaded."""
        return self.key_by_symbol.get(symbol.upper())

    def option_keys_for(self, symbol: str, expiry: str | None = None) -> list[dict]:
        """Option instrument records for a single-stock underlying (optionally one expiry). Wave 4."""
        recs = self.options_by_symbol.get(symbol.upper(), [])
        if expiry:
            recs = [r for r in recs if str(r.get("expiry")) == expiry]
        return recs

    @classmethod
    def from_records(cls, records: list[dict]) -> "InstrumentMaster":
        """Build from normalized records: each needs a name/underlying + a positive lot_size."""
        lot_by_name: dict[str, int] = {}
        for rec in records:
            name = str(rec.get("name") or rec.get("underlying") or rec.get("tradingsymbol") or "").upper()
            try:
                lot = int(float(rec.get("lot_size") or rec.get("lotsize") or 0))
            except (TypeError, ValueError):
                lot = 0
            if name and lot > 0:
                # Keep the largest seen lot for a name (index weeklies/monthlies share a name).
                lot_by_name[name] = max(lot_by_name.get(name, 0), lot)
        return cls(lot_by_name=lot_by_name, records=list(records))

    @classmethod
    def from_upstox_json(cls, data: list[dict]) -> "InstrumentMaster":
        """Upstox complete instrument dump (JSON list). Uses ``name`` + ``lot_size`` for F&O rows, and
        also indexes spot/cash instrument_keys (EQ/INDEX) + per-stock option records."""
        recs = [
            {"name": d.get("name") or d.get("underlying_symbol"), "lot_size": d.get("lot_size"),
             "instrument_type": d.get("instrument_type"), "tradingsymbol": d.get("trading_symbol")}
            for d in data
            if (d.get("segment") or "").upper().endswith("FO") or d.get("lot_size")
        ]
        m = cls.from_records(recs)
        for d in data:
            seg = (d.get("segment") or "").upper()
            key = d.get("instrument_key")
            sym = (d.get("trading_symbol") or d.get("name") or "").upper()
            if not key:
                continue
            if seg.endswith("_EQ") or seg.endswith("_INDEX") or seg.endswith("INDEX"):
                if sym:
                    # Prefer NSE keys (where single-stock F&O trades) over BSE for the same symbol —
                    # a BSE_EQ spot key has no option chain, so it must not win the resolution.
                    prev = m.key_by_symbol.get(sym)
                    if prev is None or (seg.startswith("NSE") and not str(prev).startswith("NSE")):
                        m.key_by_symbol[sym] = key
            elif seg.endswith("FO") and (d.get("instrument_type") or "").upper() in ("CE", "PE"):
                under = (d.get("underlying_symbol") or d.get("name") or "").upper()
                if under:
                    m.options_by_symbol.setdefault(under, []).append({
                        "instrument_key": key,
                        "trading_symbol": d.get("trading_symbol"),
                        "strike": d.get("strike_price"),
                        "option_type": d.get("instrument_type"),
                        "expiry": d.get("expiry"),
                        "lot_size": d.get("lot_size"),
                    })
        return m

    @classmethod
    def from_kite_csv(cls, text: str) -> "InstrumentMaster":
        """Kite instruments.csv (columns include name, lot_size, segment)."""
        rows = list(csv.DictReader(io.StringIO(text)))
        recs = [{"name": r.get("name"), "lot_size": r.get("lot_size"), "tradingsymbol": r.get("tradingsymbol")}
                for r in rows if (r.get("segment") or "").upper() in ("NFO-OPT", "NFO-FUT", "BFO-OPT", "BFO-FUT")]
        return cls.from_records(recs)


_MASTER: InstrumentMaster | None = None


def get_master() -> InstrumentMaster:
    """Process-wide instrument master (empty → config fallback until a dump is loaded)."""
    global _MASTER
    if _MASTER is None:
        _MASTER = InstrumentMaster()
    return _MASTER


def set_master(master: InstrumentMaster) -> None:
    global _MASTER
    _MASTER = master


def _cache_path() -> Path:
    d = Path("data") / "instruments_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "upstox_complete.json"


def load_cached_instruments(path: str | None = None) -> InstrumentMaster | None:
    """Build + install the process-wide master from a cached Upstox dump; None if no cache exists."""
    p = Path(path) if path else _cache_path()
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    m = InstrumentMaster.from_upstox_json(data)
    set_master(m)
    return m


def fetch_and_cache_instruments(*, url: str = _UPSTOX_DUMP_URL, timeout: float = 60.0) -> dict:
    """Download the Upstox complete instrument dump, cache it, build + install the master. Best-effort:
    on failure degrade to the cached dump (never raises). Masters drift — refresh daily."""
    import httpx

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as cli:
            r = cli.get(url)
            r.raise_for_status()
            content = r.content
        raw = gzip.decompress(content) if url.endswith(".gz") else content
        data = json.loads(raw)
        _cache_path().write_text(json.dumps(data), encoding="utf-8")
        m = InstrumentMaster.from_upstox_json(data)
        set_master(m)
        return {"ok": True, "instruments": len(data), "spot_keys": len(m.key_by_symbol),
                "option_underlyings": len(m.options_by_symbol), "path": str(_cache_path())}
    except Exception as e:  # noqa: BLE001 - network/anti-bot fragility; degrade to cache
        m = load_cached_instruments()
        return {"ok": False, "error": str(e)[:200], "from_cache": m is not None,
                "spot_keys": len(m.key_by_symbol) if m else 0}
