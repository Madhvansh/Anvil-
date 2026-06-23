"""Full-depth certification orchestrator (Wave 5).

Runs the index tip backtest (PARALLEL + streaming, so the whole bhavcopy cache is tractable in bounded
memory) and, optionally, the single-stock equity backtest across the cache, writing per-cell verdicts to
the TipValidationStore. The LOCKED validation/aggregate/gate0 formulas are untouched — this only feeds
them MORE independent-day evidence so a genuine edge can clear Harvey-t (t = SR·√n) honestly. A spurious
cell still fails DSR/PBO/OOF, so more data cannot manufacture a false positive.
"""

from __future__ import annotations


def run_full_cert(
    cache_dir, underlyings, ledger, store, *, start=None, end=None, workers: int = 0,
    equities: bool = False, universe_size: int = 40, max_expiries: int = 2,
    n_trials: int | None = None, issued_store=None, min_samples: int | None = None,
    updated_ts: str = "",
) -> dict:
    """Certify index (+optionally equity) cells across the cache. Returns a summary with per-engine
    results and the total headline-eligible cell count (what flips ``gate0_passed``)."""
    from ..ledger.ledger import MIN_SAMPLES_FOR_SCORE
    from .tip_backtest import run_tip_backtest_parallel

    ms = MIN_SAMPLES_FOR_SCORE if min_samples is None else min_samples
    out: dict = {}

    out["index"] = run_tip_backtest_parallel(
        cache_dir, underlyings, ledger, store, start=start, end=end, workers=workers,
        max_expiries=max_expiries, n_trials=n_trials, issued_store=issued_store,
        min_samples=ms, updated_ts=updated_ts)

    if equities:
        from ..tips.equities import discover_universe, run_equity_backtest
        from .data import BhavcopyArchive

        uni = discover_universe(cache_dir, top_n=universe_size)
        # Equity path is memory-light (close series + STF-OI only), so a full in-memory archive is fine.
        arch = BhavcopyArchive.from_cache_dir(cache_dir, universe=set(uni))
        out["equity"] = run_equity_backtest(
            arch, uni, ledger, store, start=start, end=end, min_samples=ms,
            n_trials=n_trials, issued_store=issued_store, updated_ts=updated_ts)

    out["headline_cells"] = (
        out["index"]["headline_cells"] + (out.get("equity", {}).get("headline_cells", 0)))
    return out
