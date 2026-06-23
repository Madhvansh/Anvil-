"""Point-in-time EOD archive for the backtester.

``chains_on(d)`` exposes *only* the rows dated ``d`` (the bhavcopy for that trading day),
so by construction a backtest cannot read a future row to build a past forecast. The realized
settlement used for resolution comes from ``index_close_on(expiry_date, underlying)`` — the
official cash close read on the expiry date itself.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from ..ingest.bhavcopy import BhavRow, build_chains, parse_fo_bhavcopy
from ..models import OptionChain

_DATE_IN_NAME = re.compile(r"(\d{4}-\d{2}-\d{2})")


@dataclass
class BhavcopyArchive:
    # date-iso -> parsed bhavcopy rows for that day
    rows_by_date: dict[str, list[BhavRow]] = field(default_factory=dict)
    # date-iso -> {UNDERLYING: index cash close}
    index_close: dict[str, dict[str, float]] = field(default_factory=dict)
    # lazily-built {date-iso: {SYMBOL: cash close}} from each row's UndrlygPric (covers single stocks)
    _equity_closes: dict[str, dict[str, float]] | None = field(default=None, repr=False)

    @classmethod
    def from_csv_texts(
        cls, texts: dict[str, str], index_close: dict[str, dict[str, float]] | None = None,
        *, universe: set[str] | None = None,
    ) -> "BhavcopyArchive":
        """Build from {date-iso: bhavcopy_csv_text}. Days with no F&O CSV (e.g. expiry-only
        resolution days) can be passed as empty strings — they still count as trading days. Pass a
        ``universe`` of single-stock symbols to ALSO retain their STO/STF rows (default: index-only)."""
        rows = {
            d: (parse_fo_bhavcopy(t, index_only=(universe is None), universe=universe) if t.strip() else [])
            for d, t in texts.items()
        }
        return cls(rows_by_date=rows, index_close=index_close or {})

    @classmethod
    def from_cache_dir(cls, cache_dir: str | Path, *, universe: set[str] | None = None) -> "BhavcopyArchive":
        """Build from a directory of cached bhavcopy CSVs (filenames containing an ISO date,
        e.g. ``fo_2026-06-12.csv``). An optional ``index_close.json`` ({date: {UND: close}})
        supplies cash closes; when absent, each day's front-month futures settlement is used as
        the index proxy (basis → 0 at expiry, so expiry-day resolution stays accurate). Pass a
        ``universe`` to also retain single-stock rows for the equities engine."""
        d = Path(cache_dir)
        texts: dict[str, str] = {}
        for csv_path in sorted(d.glob("*.csv")):
            m = _DATE_IN_NAME.search(csv_path.name)
            if m:
                texts[m.group(1)] = csv_path.read_text(encoding="utf-8", errors="replace")
        arch = cls.from_csv_texts(texts, universe=universe)
        # Full-coverage resolution: front-future settlement (available for EVERY cached day) is the base
        # index proxy; overlay cash closes from index_close.json (more precise) where present. A PARTIAL
        # index_close.json must NOT cap resolution to its few days (it silently did — older tips never
        # resolved), so we merge rather than replace.
        ff = arch.front_future_index_close()
        idx_file = d / "index_close.json"
        if idx_file.exists():
            for dd, m in json.loads(idx_file.read_text()).items():
                ff.setdefault(dd, {}).update(m)
        arch.index_close = ff
        return arch

    @staticmethod
    def cache_dates(cache_dir, start: date | None = None, end: date | None = None) -> list[date]:
        """Sorted trading dates present in a bhavcopy cache dir — read from FILENAMES only (no parse), so
        a streaming backtest can build its day-index without loading the whole directory."""
        out: list[date] = []
        for csv_path in Path(cache_dir).glob("*.csv"):
            m = _DATE_IN_NAME.search(csv_path.name)
            if not m:
                continue
            di = date.fromisoformat(m.group(1))
            if (start and di < start) or (end and di > end):
                continue
            out.append(di)
        return sorted(out)

    @classmethod
    def iter_days(cls, cache_dir, *, start: date | None = None, end: date | None = None,
                  universe: set[str] | None = None, window: int = 0):
        """STREAMING archive (Wave-5 memory fix): yield ``(date, day_archive)`` parsing ONE bhavcopy CSV
        at a time — never holding the whole directory in memory (``from_cache_dir`` loads all 626 days).

        The small ``index_close.json`` (all dates) is loaded ONCE so FORWARD expiry resolution still works
        while the heavy per-strike rows stream. ``window > 0`` keeps a rolling trailing window of days in
        the yielded archive (for momentum/equity series); else each yielded archive holds exactly one day.
        With no ``index_close.json``, each window's front-future settlement is the index proxy. Keep
        ``from_cache_dir`` for small ranges/tests; use this for full-depth certification."""
        from collections import deque

        d = Path(cache_dir)
        idx_file = d / "index_close.json"
        index_close = json.loads(idx_file.read_text()) if idx_file.exists() else None

        dated: list[tuple[str, Path]] = []
        for csv_path in d.glob("*.csv"):
            m = _DATE_IN_NAME.search(csv_path.name)
            if m:
                dated.append((m.group(1), csv_path))
        dated.sort()

        win: deque | None = deque(maxlen=window) if window and window > 0 else None
        for d_iso, path in dated:
            di = date.fromisoformat(d_iso)
            if (start and di < start) or (end and di > end):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rows = (parse_fo_bhavcopy(text, index_only=(universe is None), universe=universe)
                    if text.strip() else [])
            if win is not None:
                win.append((d_iso, rows))
                rows_by_date = dict(win)
            else:
                rows_by_date = {d_iso: rows}
            arch = cls(rows_by_date=rows_by_date)
            # Full-coverage resolution (same rule as from_cache_dir): this window's front-future closes as
            # the base, overlaid by any cash closes from index_close.json — so a partial json never caps it.
            ff = arch.front_future_index_close()
            if index_close:
                for dd, m in index_close.items():
                    ff.setdefault(dd, {}).update(m)
            arch.index_close = ff
            yield di, arch

    def front_future_index_close(self) -> dict[str, dict[str, float]]:
        """Per (date, underlying), the nearest-expiry future settlement — an index proxy used
        when no separate cash-close feed is supplied. Documented approximation: futures and
        cash converge at expiry, so the realized level used for resolution is accurate."""
        out: dict[str, dict[str, float]] = {}
        for d_iso, rows in self.rows_by_date.items():
            front: dict[str, tuple[str, float]] = {}
            for r in rows:
                if r.is_future and r.settle > 0:
                    cur = front.get(r.symbol)
                    if cur is None or r.expiry < cur[0]:
                        front[r.symbol] = (r.expiry, r.settle)
            if front:
                out[d_iso] = {u: s for u, (_, s) in front.items()}
        return out

    def trading_days(self, start: date | None = None, end: date | None = None) -> list[date]:
        days = [date.fromisoformat(s) for s in sorted(self.rows_by_date)]
        if start:
            days = [d for d in days if d >= start]
        if end:
            days = [d for d in days if d <= end]
        return days

    def index_close_on(self, d: date, underlying: str) -> float | None:
        return self.index_close.get(d.isoformat(), {}).get(underlying.upper())

    def chains_on(self, d: date) -> list[OptionChain]:
        rows = self.rows_by_date.get(d.isoformat(), [])
        return build_chains(rows, asof=d, index_close=self.index_close.get(d.isoformat()))

    # ---- single-stock (equity) accessors ----------------------------------
    # The CASH close of every F&O underlying is carried on each row (UndrlygPric); the equity engine
    # uses it both as the daily price series (momentum/reversion) and as the resolution level N days
    # out. STF rows additionally give futures OI for the long/short-buildup signal.
    def equity_closes(self) -> dict[str, dict[str, float]]:
        if self._equity_closes is None:
            out: dict[str, dict[str, float]] = {}
            for d_iso, rows in self.rows_by_date.items():
                day: dict[str, float] = {}
                for r in rows:
                    if r.underlying_price > 0:
                        day[r.symbol] = r.underlying_price  # identical across a symbol's rows
                if day:
                    out[d_iso] = day
            self._equity_closes = out
        return self._equity_closes

    def equity_close_on(self, d: date, symbol: str) -> float | None:
        return self.equity_closes().get(d.isoformat(), {}).get(symbol.upper())

    def equity_close_series(self, symbol: str, upto: date | None = None) -> list[tuple[str, float]]:
        """Ascending [(date_iso, cash_close)] for ``symbol`` on/before ``upto`` (point-in-time)."""
        sym = symbol.upper()
        upto_iso = upto.isoformat() if upto else None
        out: list[tuple[str, float]] = []
        for d_iso in sorted(self.equity_closes()):
            if upto_iso is not None and d_iso > upto_iso:
                break
            px = self.equity_closes()[d_iso].get(sym)
            if px is not None:
                out.append((d_iso, px))
        return out

    def equity_meta_on(self, d: date, symbol: str) -> dict | None:
        """{close, stf_oi, stf_oi_change, lot_size} for ``symbol`` on day ``d`` (None if absent)."""
        sym = symbol.upper()
        rows = self.rows_by_date.get(d.isoformat(), [])
        close = stf_oi = stf_oi_chg = 0.0
        lot = 0
        seen = False
        for r in rows:
            if r.symbol != sym:
                continue
            seen = True
            if r.underlying_price > 0:
                close = r.underlying_price
            if r.lot_size > 0 and lot == 0:
                lot = r.lot_size
            if r.is_future:
                stf_oi, stf_oi_chg = r.oi, r.oi_change
        if not seen:
            return None
        return {"close": close, "stf_oi": stf_oi, "stf_oi_change": stf_oi_chg, "lot_size": lot}

    def equity_universe(self, top_n: int | None = None) -> list[str]:
        """Single-stock symbols present in the archive (those carrying STO/STF rows), ranked by
        total option volume on the latest day. ``top_n`` keeps only the most liquid names."""
        from ..config import SUPPORTED_INDEXES

        vol: dict[str, float] = {}
        for rows in self.rows_by_date.values():
            for r in rows:
                if r.symbol in SUPPORTED_INDEXES:
                    continue
                vol[r.symbol] = vol.get(r.symbol, 0.0) + (r.volume or 0.0)
        ranked = sorted(vol, key=lambda s: vol[s], reverse=True)
        return ranked[:top_n] if top_n else ranked
