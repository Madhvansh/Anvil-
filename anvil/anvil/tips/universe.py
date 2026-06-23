"""Dynamic single-stock universe selection — stage 1 of the live stock-tips funnel.

The owner's requirement: stock tips must NOT be a fixed handful — the universe should be the
most-liquid + highest-momentum (maximum-opportunity) F&O names, chosen fresh each cycle. This module
is the CHEAP screen that picks WHICH stocks to deep-analyse; the expensive per-stock live chain +
greeks + momentum analysis (the "monetization opportunity" read) happens in stage 2 (``tips.stocks``).

Cheap by construction — no per-stock live API calls here:
  * liquidity  — total option volume on the latest cached bhavcopy day (``discover_universe``), or the
    instrument master's F&O-stock list as a fallback;
  * momentum   — 12-1 price momentum from the Yahoo daily-close cache (cache-first, offline-safe).

Every source degrades to the next, and finally to ``SETTINGS.stock_options_universe`` so the selector
is never empty.
"""

from __future__ import annotations

from ..config import SETTINGS, SUPPORTED_INDEXES
from ..factors.equities import momentum_12_1
from ..ingest import yahoo

_DEFAULT_CACHE_DIR = "data/bhavcopy_cache"


def _liquidity_pool(screen_n: int, cache_dir: str | None) -> list[str]:
    """Top-``screen_n`` F&O single stocks by latest-day option volume (bhavcopy). [] if no cache."""
    from .equities import discover_universe

    try:
        return discover_universe(cache_dir or _DEFAULT_CACHE_DIR, top_n=screen_n)
    except Exception:  # noqa: BLE001 - cache missing/unreadable → caller falls through
        return []


def _instrument_pool(screen_n: int) -> list[str]:
    """F&O single-stock underlyings from the loaded Upstox instrument master (unranked)."""
    try:
        from ..ingest.instruments import get_master

        syms = [s for s in get_master().options_by_symbol if s not in SUPPORTED_INDEXES]
        return sorted(syms)[:screen_n]
    except Exception:  # noqa: BLE001
        return []


def _fallback_universe(top_n: int) -> list[str]:
    """The configured floor — used only when no data-backed pool can be built."""
    syms = [s.strip().upper() for s in SETTINGS.stock_options_universe.split(",") if s.strip()]
    return syms[:top_n]


def _momentum_strength(symbol: str) -> float:
    """|12-1 momentum| in [0,1] from the Yahoo daily-close cache; 0.0 when no history is cached."""
    try:
        sym = yahoo.INDEX_SYMBOL.get(symbol.upper(), f"{symbol.upper()}.NS")
        closes = [float(b["c"]) for b in yahoo.read_cache(sym)]
        if len(closes) < 14:
            return 0.0
        sig = momentum_12_1(closes)
        return float(sig.strength) if sig.active else 0.0
    except Exception:  # noqa: BLE001 - history is best-effort
        return 0.0


def select_universe(top_n: int | None = None, screen_n: int | None = None, *,
                    cache_dir: str | None = None) -> list[str]:
    """The dynamic stock universe to deep-analyse: a liquidity-screened pool re-ranked by a
    liquidity+momentum composite, trimmed to ``top_n``. Never empty (falls back to the config floor)."""
    top_n = top_n or SETTINGS.stock_universe_top_n
    screen_n = max(top_n, screen_n or SETTINGS.stock_universe_screen_n)

    pool = _liquidity_pool(screen_n, cache_dir) or _instrument_pool(screen_n)
    if not pool:
        return _fallback_universe(top_n)

    n = len(pool)
    scored: list[tuple[str, float]] = []
    for i, sym in enumerate(pool):
        liquidity_rank = 1.0 - (i / n)  # 1.0 = most liquid (pool is liquidity-ordered)
        momentum = _momentum_strength(sym)
        scored.append((sym, 0.5 * liquidity_rank + 0.5 * momentum))
    scored.sort(key=lambda x: -x[1])
    out = [s for s, _ in scored[:top_n]]
    return out or _fallback_universe(top_n)
