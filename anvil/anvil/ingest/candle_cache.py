"""Fetch + persist multi-timeframe candles into the BarStore — the candle analogue of
``yahoo.fetch_and_cache``: best-effort fetch per timeframe, **degrade to whatever is already stored**,
never raise. The BarStore (DuckDB, idempotent) IS the cache, so a re-run only fills gaps / refreshes
the forming bar. A connector is injected (Upstox for live; any object with ``get_candles``) which keeps
this offline-testable and source-agnostic like the rest of ``anvil.ingest``.
"""

from __future__ import annotations

from ..store.bars import BarStore

# Default ladder of timeframes for the momentum substrate (coarse→fine).
DEFAULT_TFS = ("1d", "1h", "15m", "5m", "1m")


def fetch_candles(
    connector, symbol: str, tfs=DEFAULT_TFS, *,
    from_date: str | None = None, to_date: str | None = None,
    intraday: bool = False, store: BarStore | None = None,
) -> dict:
    """Fetch each timeframe via ``connector.get_candles`` and write to the BarStore. Returns a summary
    ``{symbol, by_tf: {tf: rows_written}, stored: {tf: rows_in_store}, errors: {tf: msg}}``. A failed
    timeframe is logged in ``errors`` and the run continues (degrade, never raise)."""
    own = store is None
    store = store or BarStore()
    sym = symbol.upper()
    summary: dict = {"symbol": sym, "by_tf": {}, "stored": {}, "errors": {}}
    try:
        for tf in tfs:
            try:
                bars = connector.get_candles(symbol, tf, from_date=from_date, to_date=to_date, intraday=intraday)
                summary["by_tf"][tf] = store.write_bars(bars)
            except Exception as e:  # noqa: BLE001 - source fragility; degrade to what's stored
                summary["errors"][tf] = str(e)[:200]
                summary["by_tf"][tf] = 0
            summary["stored"][tf] = len(store.bars(sym, tf))
    finally:
        if own:
            store.close()
    return summary
