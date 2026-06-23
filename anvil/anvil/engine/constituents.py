"""Cross-sectional constituent → index aggregation (Innovation I.3) — the research report's #1 novel,
India-specific angle.

The ~5 heaviest BankNifty names carry ~82% of the index, so a *weighted* view of the heavyweights
(their momentum / direction) aggregates into an index bias, and stock→index **lead-lag** can be
exploited (a heavyweight's move often precedes the index print). Pure-numpy, NO I/O — callers supply the
per-constituent reads (from Wave-2 momentum on Wave-4 single-stock data). Honesty: returns weighted
breadth / agreement / coverage and a measurable lead-lag correlation — never an accuracy %; abstains on
thin coverage (coverage is always disclosed).
"""

from __future__ import annotations

import numpy as np

# Direction tags — string-identical to ``strategy.types`` (the engine tier stays strategy-free).
NEUTRAL = "neutral"
BULLISH = "bullish"
BEARISH = "bearish"

# Approximate free-float index weights (%) for the heavyweight constituents. These DRIFT with rebalances —
# treat as a documented default; a live index-weight feed should override via ``weights=``. (~2025 NSE.)
INDEX_WEIGHTS: dict[str, dict[str, float]] = {
    "BANKNIFTY": {"HDFCBANK": 28.0, "ICICIBANK": 24.0, "SBIN": 9.0, "AXISBANK": 9.0, "KOTAKBANK": 8.0},
    "NIFTY": {"HDFCBANK": 12.0, "RELIANCE": 9.0, "ICICIBANK": 8.0, "INFY": 6.0, "TCS": 4.0,
              "ITC": 4.0, "LT": 4.0, "AXISBANK": 3.0, "KOTAKBANK": 3.0, "SBIN": 3.0},
}


def index_weights(index: str) -> dict[str, float]:
    """Default constituent weights for an index (empty dict if unknown)."""
    return dict(INDEX_WEIGHTS.get(index.upper(), {}))


def weighted_breadth(directions: dict[str, str], weights: dict[str, float]) -> dict | None:
    """Net weighted directional breadth across constituents. ``directions`` maps symbol→tag. Returns
    ``net_breadth`` (bullish-weight minus bearish-weight over covered weight, −1..1), the index ``bias``,
    and disclosed ``coverage`` (covered weight / total). None if no overlap / zero total weight."""
    total = sum(weights.values())
    if total <= 0:
        return None
    seen = bull = bear = 0.0
    n = 0
    for sym, w in weights.items():
        d = directions.get(sym)
        if d is None:
            continue
        seen += w
        n += 1
        if d == BULLISH:
            bull += w
        elif d == BEARISH:
            bear += w
    if seen <= 0:
        return None
    net = (bull - bear) / seen
    bias = BULLISH if net > 0.15 else (BEARISH if net < -0.15 else NEUTRAL)
    return {"net_breadth": float(net), "coverage": float(seen / total), "n": n,
            "bias": bias, "bull_weight": float(bull), "bear_weight": float(bear)}


def aggregate_strength(reads: dict[str, dict], weights: dict[str, float]) -> dict | None:
    """Weighted aggregate of per-symbol ``{direction, strength}`` reads → index ``signed_strength``
    (−1..1), ``bias``, ``strength`` (|signed|), and disclosed ``coverage``. None if no covered weight."""
    total = sum(weights.values())
    if total <= 0:
        return None
    num = seen = 0.0
    for sym, w in weights.items():
        r = reads.get(sym)
        if not r:
            continue
        d = r.get("direction")
        s = float(r.get("strength") or 0.0)
        sign = 1.0 if d == BULLISH else (-1.0 if d == BEARISH else 0.0)
        num += w * sign * s
        seen += w
    if seen <= 0:
        return None
    signed = num / seen
    bias = BULLISH if signed > 0.05 else (BEARISH if signed < -0.05 else NEUTRAL)
    return {"signed_strength": float(signed), "coverage": float(seen / total),
            "bias": bias, "strength": float(min(1.0, abs(signed)))}


def lead_lag(index_returns, constituent_returns, max_lag: int = 3) -> dict | None:
    """Lagged correlation of a constituent LEADING the index: the lag (1..max_lag) maximizing
    ``corr(constituent[t-lag], index[t])``, and that correlation. A high positive value = the
    constituent's move tends to PRECEDE the index's. None if the series are too short / degenerate."""
    x = np.asarray(constituent_returns, dtype=float)
    y = np.asarray(index_returns, dtype=float)
    n = min(x.size, y.size)
    if n < max_lag + 5:
        return None
    x, y = x[-n:], y[-n:]
    best_lag, best_c = 0, 0.0
    for lag in range(1, max_lag + 1):
        a, b = x[:-lag], y[lag:]
        if a.size < 3 or a.std() <= 0 or b.std() <= 0:
            continue
        c = float(np.corrcoef(a, b)[0, 1])
        if abs(c) > abs(best_c):
            best_lag, best_c = lag, c
    if best_lag == 0:
        return None
    return {"lead_lag": best_lag, "correlation": best_c}
