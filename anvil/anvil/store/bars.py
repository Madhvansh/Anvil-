"""DuckDB-backed multi-timeframe OHLCV bar store + a pure-numpy resampler.

The momentum substrate: persists per-symbol bars at several timeframes (1m/5m/15m/1h/1d/1w), keyed
``(symbol, tf, ts)`` for idempotency (re-writing the same bar UPDATES it — so the live forming bar can
be refreshed as ticks arrive). Mirrors ``store.timeseries.SnapshotStore``'s embedded-DuckDB pattern but
lives in its OWN file (``SETTINGS.bars_path``) so the always-on aggregator never contends with the
snapshot/ledger writer locks.

``resample_bars`` is a stdlib OHLCV roll-up (finer → coarser) used by the aggregator and offline builds.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import duckdb

from ..config import SETTINGS
from ..models import Bar

_SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol VARCHAR, tf VARCHAR, ts VARCHAR,
    open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE, oi DOUBLE,
    PRIMARY KEY (symbol, tf, ts)
);
"""

_TF_MINUTES = {"1m": 1, "5m": 5, "15m": 15, "30m": 30, "1h": 60}


def _parse_ts(ts: str) -> datetime:
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


def _bucket_key(ts: str, dst_tf: str) -> str:
    """Deterministic bucket label for ``ts`` at the destination timeframe (the coarse bar's ts)."""
    dt = _parse_ts(ts)
    if dst_tf in _TF_MINUTES:
        m = _TF_MINUTES[dst_tf]
        floored = dt - timedelta(minutes=dt.minute % m, seconds=dt.second, microseconds=dt.microsecond)
        return floored.isoformat()
    if dst_tf == "1d":
        return dt.date().isoformat()
    if dst_tf == "1w":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    raise ValueError(f"unsupported destination timeframe: {dst_tf!r}")


def resample_bars(bars: list[Bar], dst_tf: str) -> list[Bar]:
    """Aggregate finer bars into ``dst_tf`` OHLCV(+OI) bars. open=first, high=max, low=min, close=last,
    volume=sum, oi=last. Input need not be pre-sorted. Empty in → empty out."""
    if not bars:
        return []
    symbol = bars[0].symbol
    ordered = sorted(bars, key=lambda b: _parse_ts(b.ts))
    buckets: dict[str, list[Bar]] = {}
    order: list[str] = []
    for b in ordered:
        key = _bucket_key(b.ts, dst_tf)
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(b)
    out: list[Bar] = []
    for key in order:
        grp = buckets[key]
        ois = [g.oi for g in grp if g.oi is not None]
        out.append(Bar(
            symbol=symbol, tf=dst_tf, ts=key,
            open=grp[0].open,
            high=max(g.high for g in grp),
            low=min(g.low for g in grp),
            close=grp[-1].close,
            volume=float(sum(g.volume for g in grp)),
            oi=(ois[-1] if ois else None),
        ))
    return out


class BarStore:
    def __init__(self, path: str | None = None):
        self.path = path or SETTINGS.bars_path
        self.con = duckdb.connect(self.path)
        self.con.execute(_SCHEMA)

    def write_bars(self, bars: list[Bar]) -> int:
        """Idempotent upsert (re-writing a bar refreshes it — the live forming bar). Returns count."""
        n = 0
        for b in bars:
            self.con.execute(
                "INSERT INTO bars VALUES (?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT (symbol, tf, ts) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, "
                "close=excluded.close, volume=excluded.volume, oi=excluded.oi",
                [b.symbol, b.tf, b.ts, b.open, b.high, b.low, b.close, b.volume, b.oi],
            )
            n += 1
        return n

    def bars(self, symbol: str, tf: str, n: int | None = None, since: str | None = None) -> list[Bar]:
        """Bars for (symbol, tf) ascending by ts. ``n`` keeps the most recent n; ``since`` filters ts ≥."""
        q = "SELECT symbol, tf, ts, open, high, low, close, volume, oi FROM bars WHERE symbol=? AND tf=?"
        params: list = [symbol, tf]
        if since is not None:
            q += " AND ts >= ?"
            params.append(since)
        q += " ORDER BY ts"
        rows = self.con.execute(q, params).fetchall()
        bars = [Bar(symbol=r[0], tf=r[1], ts=r[2], open=r[3], high=r[4], low=r[5],
                    close=r[6], volume=r[7], oi=r[8]) for r in rows]
        return bars[-n:] if n else bars

    def closes(self, symbol: str, tf: str, n: int | None = None) -> list[float]:
        return [b.close for b in self.bars(symbol, tf, n=n)]

    def latest_ts(self, symbol: str, tf: str) -> str | None:
        row = self.con.execute(
            "SELECT max(ts) FROM bars WHERE symbol=? AND tf=?", [symbol, tf]
        ).fetchone()
        return row[0] if row and row[0] else None

    def count(self, symbol: str | None = None) -> int:
        if symbol:
            return self.con.execute("SELECT count(*) FROM bars WHERE symbol=?", [symbol]).fetchone()[0]
        return self.con.execute("SELECT count(*) FROM bars").fetchone()[0]

    def close(self) -> None:
        self.con.close()
