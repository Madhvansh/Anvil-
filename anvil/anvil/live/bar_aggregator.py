"""Aggregate the recorder's spot ticks into multi-timeframe OHLC bars in the BarStore.

The always-on recorder persists per-minute spot (``SnapshotStore.spot_series``); this rolls that
unbuyable history into 1m/5m/1h bars so the momentum engine has real, proprietary intraday series even
without a paid candle feed. Tick→bar reuses ``store.bars.resample_bars`` via the "point-bar" trick
(each tick = a degenerate o=h=l=c bar), so there is no bespoke bucketing to keep in sync.

Used as a supervisor sub-task and behind ``anvil data build-bars``. Injectables keep it offline-testable.
"""

from __future__ import annotations

from ..models import Bar
from ..store.bars import BarStore, resample_bars
from ..store.timeseries import SnapshotStore

DEFAULT_TFS = ("1m", "5m", "1h")


def aggregate_ticks(ticks, symbol: str, tf: str) -> list[Bar]:
    """Roll (ts, price[, volume[, oi]]) ticks into OHLC(+V/OI) bars at ``tf``. Empty in → empty out."""
    sym = symbol.upper()
    point: list[Bar] = []
    for t in ticks:
        if not t or t[1] is None:
            continue
        price = float(t[1])
        vol = float(t[2]) if len(t) > 2 and t[2] is not None else 0.0
        oi = float(t[3]) if len(t) > 3 and t[3] is not None else None
        point.append(Bar(symbol=sym, tf="tick", ts=str(t[0]),
                         open=price, high=price, low=price, close=price, volume=vol, oi=oi))
    return resample_bars(point, tf)


def build_bars_from_snapshots(
    symbol: str, tfs=DEFAULT_TFS, *,
    snap_store: SnapshotStore | None = None, bar_store: BarStore | None = None,
) -> dict:
    """Read recorded spot ticks for ``symbol`` and write aggregated bars at each ``tf`` to the BarStore.
    Returns ``{symbol, ticks, by_tf: {tf: rows_written}}``."""
    own_s = snap_store is None
    own_b = bar_store is None
    snap_store = snap_store or SnapshotStore()
    bar_store = bar_store or BarStore()
    sym = symbol.upper()
    summary: dict = {"symbol": sym, "ticks": 0, "by_tf": {}}
    try:
        ticks = snap_store.spot_series(sym)
        summary["ticks"] = len(ticks)
        for tf in tfs:
            bars = aggregate_ticks(ticks, sym, tf)
            summary["by_tf"][tf] = bar_store.write_bars(bars)
    finally:
        if own_s:
            snap_store.close()
        if own_b:
            bar_store.close()
    return summary
