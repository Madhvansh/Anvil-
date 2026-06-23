"""NSE/BSE F&O Bhavcopy (end-of-day) → normalized OptionChain objects, for the backtester.

The F&O Bhavcopy is the free, official end-of-day archive: for every option and future
contract on a trading day it publishes O/H/L/C, the **settlement price**, **open interest**
and **volume**. It is the honest source for a *real, out-of-sample* calibration backtest:

  * the **futures settlement** is the Black-76 forward (tagged ``nse_bhavcopy_settle``);
  * per-strike **settlement** prices back out IV via the implied-distribution smile;
  * OI/volume let the backtester drop contracts that never actually traded (survivorship).

Two header layouts are supported, matched by column *name* so either parses:
  * the current NSE **UDiFF** common bhavcopy (``TckrSymb``/``SttlmPric``/``OpnIntrst``…);
  * the **legacy** ``fo{DDMMMYYYY}bhav`` layout (``SYMBOL``/``SETTLE_PR``/``OPEN_INT``…).

Nothing here runs in the offline demo; it powers the backtest lab. Live NSE archives are
undocumented and anti-bot (browser-like session), so the network fetchers are best-effort —
prefer a cached/committed CSV for reproducible backtests and tests.
"""

from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

import httpx

from ..config import SUPPORTED_INDEXES, lot_size
from ..models import ChainRow, OptionChain, OptionType

# Current UDiFF archive (YYYYMMDD); legacy daily archive (kept for older history).
UDIFF_URL = "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip"
LEGACY_URL = (
    "https://archives.nseindia.com/content/historical/DERIVATIVES/"
    "{year}/{mon}/fo{ddmonyyyy}bhav.csv.zip"
)
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/csv,application/zip,*/*",
    "Referer": "https://www.nseindia.com",
}

# canonical field -> candidate header names across the supported layouts.
_COLS: dict[str, tuple[str, ...]] = {
    "symbol": ("TckrSymb", "SYMBOL"),
    "instr": ("FinInstrmTp", "INSTRUMENT"),
    "expiry": ("XpryDt", "EXPIRY_DT"),
    "strike": ("StrkPric", "STRIKE_PR"),
    "optkind": ("OptnTp", "OPTION_TYP"),
    "settle": ("SttlmPric", "SETTLE_PR"),
    "close": ("ClsPric", "CLOSE"),
    "oi": ("OpnIntrst", "OPEN_INT"),
    "oichg": ("ChngInOpnIntrst", "CHG_IN_OI"),
    "vol": ("TtlTradgVol", "CONTRACTS"),
    # UDiFF-only (absent in the legacy layout → handled as 0 / fallback):
    "undr": ("UndrlygPric",),  # the underlying's CASH price on the row — exact spot & resolution level
    "lot": ("NewBrdLotQty", "MKT_LOT"),  # contract lot size (true for single stocks, which INDEX_LOT_SIZE lacks)
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


@dataclass
class BhavRow:
    symbol: str
    is_option: bool
    is_future: bool
    expiry: str  # ISO date
    strike: float | None
    option_type: OptionType | None
    settle: float
    close: float
    oi: float
    oi_change: float
    volume: float
    underlying_price: float = 0.0  # the underlying's CASH price (UDiFF only; 0 on the legacy layout)
    lot_size: int = 0  # contract lot size from the bhavcopy (0 when the column is absent)


def _f(v) -> float:
    try:
        s = str(v).strip().replace(",", "")
        return float(s) if s and s not in ("-", "NA") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _iso_date(v) -> str:
    """Parse either ISO (``2026-06-26``) or legacy day-first (``26-JUN-2026``)."""
    s = (v or "").strip()
    if not s:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s  # leave as-is; callers compare strings


def _pick(header: list[str], names: tuple[str, ...]) -> str | None:
    return next((h for h in names if h in header), None)


def parse_fo_bhavcopy(
    text: str, *, index_only: bool = True, universe: set[str] | None = None
) -> list[BhavRow]:
    """Parse a F&O bhavcopy CSV (header auto-detected).

    Keep rule: when ``universe`` is given, keep those symbols (plus the indexes, which are cheap);
    else when ``index_only`` (default) keep only the index F&O we forecast; else keep everything.
    Single-stock options (``STO``) and futures (``STF``) parse exactly like index ones — they were
    only filtered out before. The UDiFF ``UndrlygPric``/``NewBrdLotQty`` columns are captured when
    present (the legacy layout lacks them → 0)."""
    reader = csv.DictReader(io.StringIO(text))
    fields = reader.fieldnames or []
    col = {k: _pick(fields, names) for k, names in _COLS.items()}
    if not col["symbol"] or not col["settle"]:
        raise ValueError("Unrecognized bhavcopy layout (missing symbol/settle columns)")
    uni = {u.upper() for u in universe} if universe else None
    rows: list[BhavRow] = []
    for raw in reader:
        sym = (raw.get(col["symbol"]) or "").strip().upper()
        if uni is not None:
            if sym not in uni and sym not in SUPPORTED_INDEXES:
                continue
        elif index_only and sym not in SUPPORTED_INDEXES:
            continue
        optk = (raw.get(col["optkind"]) or "").strip().upper()
        is_opt = optk in ("CE", "PE")
        instr = (raw.get(col["instr"]) or "").strip().upper()
        is_fut = (not is_opt) and ("FUT" in instr or instr in ("IDF", "STF"))
        if not (is_opt or is_fut):
            continue
        rows.append(
            BhavRow(
                symbol=sym,
                is_option=is_opt,
                is_future=is_fut,
                expiry=_iso_date(raw.get(col["expiry"])),
                strike=_f(raw.get(col["strike"])) if is_opt else None,
                option_type=OptionType(optk) if is_opt else None,
                settle=_f(raw.get(col["settle"])),
                close=_f(raw.get(col["close"])),
                oi=_f(raw.get(col["oi"])),
                oi_change=_f(raw.get(col["oichg"])),
                volume=_f(raw.get(col["vol"])),
                underlying_price=_f(raw.get(col["undr"])) if col["undr"] else 0.0,
                lot_size=int(_f(raw.get(col["lot"]))) if col["lot"] else 0,
            )
        )
    return rows


def build_chains(
    rows: list[BhavRow],
    *,
    asof: date,
    index_close: dict[str, float] | None = None,
    min_strikes: int = 4,
) -> list[OptionChain]:
    """Group bhavcopy rows into per-(underlying, expiry) OptionChains.

    The futures settlement is used as the Black-76 forward (``future_price_source =
    'nse_bhavcopy_settle'``). ``index_close`` supplies each underlying's cash close for the
    day (used as ``spot`` and, on expiry day, as the realized settlement level); if absent we
    fall back to the futures settle. Expiries already settled on/before ``asof`` are skipped —
    a chain is only built for live (unexpired) contracts as of the trading day.
    """
    index_close = index_close or {}
    by_key: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r.symbol, r.expiry)
        grp = by_key.setdefault(key, {"opts": [], "fut": None})
        if r.is_future:
            grp["fut"] = r
        elif r.is_option:
            grp["opts"].append(r)

    asof_iso = asof.isoformat()
    ts = f"{asof_iso}T15:30:00+05:30"
    chains: list[OptionChain] = []
    for (sym, expiry), grp in by_key.items():
        if expiry and expiry <= asof_iso:  # don't build an already-expired chain
            continue
        opts = grp["opts"]
        if len(opts) < min_strikes:
            continue
        fut: BhavRow | None = grp["fut"]
        fprice = fut.settle if (fut and fut.settle > 0) else None
        # Exact cash price from the bhavcopy (UndrlygPric) — better than the futures-settle proxy,
        # and the only spot source for single stocks (which have no index_close feed).
        undr = next((o.underlying_price for o in opts if o.underlying_price > 0), 0.0)
        spot = index_close.get(sym)
        if spot is None:
            spot = float(undr) if undr > 0 else (float(fprice) if fprice else float(opts[0].strike or 0.0))
        chain_rows = [
            ChainRow(
                strike=float(o.strike),
                option_type=o.option_type,
                ltp=o.settle if o.settle > 0 else (o.close or None),
                oi=o.oi,
                oi_change=o.oi_change,
                volume=o.volume,
            )
            for o in opts
        ]
        # Lot size: indexes keep the configured value (preserves existing index backtests); single
        # stocks take the true lot from the bhavcopy (INDEX_LOT_SIZE has no stock entries).
        lot = lot_size(sym)
        if sym not in SUPPORTED_INDEXES:
            bhav_lot = next((o.lot_size for o in opts if o.lot_size > 0), 0)
            lot = bhav_lot or lot
        chains.append(
            OptionChain(
                underlying=sym,
                spot=float(spot),
                expiry=expiry,
                timestamp=ts,
                rows=chain_rows,
                future_price=float(fprice) if fprice else None,
                future_price_source="nse_bhavcopy_settle" if fprice else None,
                lot_size=lot,
            )
        )
    return chains


# ---- best-effort network fetch (reproducible backtests should cache the CSV) ----
def _unzip_single_csv(blob: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        return zf.read(name).decode("utf-8", errors="replace")


class RateLimited(RuntimeError):
    """NSE answered 429/503 — the caller should back off for at least ``retry_after`` seconds. Surfaced
    (instead of silently treated as a miss) so the backfill can honor the server's pace on a long pull."""

    def __init__(self, retry_after: float = 0.0):
        super().__init__(f"rate-limited (retry-after={retry_after}s)")
        self.retry_after = float(retry_after or 0.0)


def _retry_after_seconds(resp) -> float:
    """Parse a ``Retry-After`` header (delta-seconds; HTTP-date form is treated as 'unknown' → 0)."""
    raw = (resp.headers.get("Retry-After") or "").strip()
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return 0.0


def fetch_bhavcopy_text(d: date, *, timeout: float = 20.0) -> str:
    """Download + unzip one date's NSE F&O bhavcopy (UDiFF, falling back to legacy).
    Raises ``RateLimited`` on 429/503 (caller backs off ≥ Retry-After) and ``RuntimeError`` on a
    holiday/layout miss — callers should cache and treat NSE as fragile."""
    ymd = d.strftime("%Y%m%d")
    legacy = LEGACY_URL.format(
        year=d.year, mon=_MONTHS[d.month - 1], ddmonyyyy=f"{d.day:02d}{_MONTHS[d.month - 1]}{d.year}"
    )
    with httpx.Client(timeout=timeout, headers=_BROWSER_HEADERS, follow_redirects=True) as c:
        c.get("https://www.nseindia.com")  # warm anti-bot cookies
        for url in (UDIFF_URL.format(ymd=ymd), legacy):
            try:
                r = c.get(url)
                if r.status_code == 200 and r.content:
                    return _unzip_single_csv(r.content)
                if r.status_code in (429, 503):
                    # Host-level throttle — don't hammer the legacy URL on the same host; surface it.
                    raise RateLimited(_retry_after_seconds(r))
            except (httpx.HTTPError, zipfile.BadZipFile, StopIteration):
                continue
    raise RuntimeError(f"Could not fetch F&O bhavcopy for {d.isoformat()} (holiday or layout change)")


def fetch_chains(d: date, *, index_close: dict[str, float] | None = None) -> list[OptionChain]:
    return build_chains(parse_fo_bhavcopy(fetch_bhavcopy_text(d)), asof=d, index_close=index_close)
