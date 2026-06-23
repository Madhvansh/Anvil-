"""Assemble the optional time-series block a caller attaches to a chain so momentum/flow factors fire.

This is the bridge from the data layer (Yahoo daily closes, the BarStore's multi-timeframe bars, the
SnapshotStore's recorded GEX/IV history) into ``SignalContext(... **series)``. Offline-safe: daily closes
come cache-first from Yahoo; bar/flow series are read ONLY from injected stores (no DuckDB opened per
tick — avoids contention with the recorder/supervisor), and every source degrades to omission so the
returned block is always valid and the legacy chain-only path is recovered when nothing is available.
"""

from __future__ import annotations

from ..ingest import yahoo

# Coarse→fine timeframes pulled from the BarStore when one is supplied.
DEFAULT_TFS = ("1m", "5m", "15m", "1h", "1d")


def build_series_block(
    underlying: str, *, bar_store=None, snap_store=None, tfs=DEFAULT_TFS, n: int = 250,
) -> dict:
    """Return ``{closes?, bars_by_tf?, flow_series?}`` for ``underlying``.

    - ``closes`` — daily closes from the Yahoo cache (always attempted; cache-first, offline-safe).
    - ``bars_by_tf`` — per-timeframe close series from an injected ``bar_store`` (falls back to the
      daily closes as the ``1d`` timeframe when the store has none).
    - ``flow_series`` — GEX / IV-rank velocity inputs from an injected ``snap_store``.
    A key is present only when ≥ 2 observations exist; an empty dict => the legacy chain-only context."""
    block: dict = {}

    closes: list[float] = []
    try:
        # CACHE-ONLY (never fetch on a live tick): the closes cache is populated by the scheduled
        # `anvil data fetch-closes` / supervisor; a missing cache simply means momentum abstains.
        sym = yahoo.INDEX_SYMBOL.get(underlying.upper(), f"{underlying.upper()}.NS")
        bars = yahoo.read_cache(sym)
        closes = [float(b["c"]) for b in bars][-n:]
    except Exception:  # noqa: BLE001 - history is best-effort; absence => abstain
        closes = []
    if len(closes) >= 2:
        block["closes"] = closes

    if bar_store is not None:
        bbt: dict[str, list[float]] = {}
        for tf in tfs:
            try:
                cl = bar_store.closes(underlying, tf, n=n)
            except Exception:  # noqa: BLE001
                cl = []
            if len(cl) >= 2:
                bbt[tf] = cl
        if "1d" not in bbt and len(closes) >= 2:
            bbt["1d"] = closes
        if bbt:
            block["bars_by_tf"] = bbt
    elif len(closes) >= 2:
        block["bars_by_tf"] = {"1d": closes}

    if snap_store is not None:
        flow: dict[str, list[float]] = {}
        try:
            rows = list(reversed(snap_store.latest(underlying, n)))   # latest() is DESC → ascending
            gex = [float(r[2]) for r in rows if r[2] is not None]
            if len(gex) >= 2:
                flow["gex_series"] = gex
        except Exception:  # noqa: BLE001
            pass
        try:
            ivh = [float(x) for x in snap_store.iv_history(underlying)][-n:]
            if len(ivh) >= 2:
                flow["iv_rank_series"] = ivh
        except Exception:  # noqa: BLE001
            pass
        if flow:
            block["flow_series"] = flow

    return block
