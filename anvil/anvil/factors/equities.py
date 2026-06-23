"""Single-stock directional factors — the cross-sectional model behind cash-equity BUY/SELL tips.

Single stocks have thin, often illiquid option chains, so the equity edge is DIRECTIONAL and
RELATIVE (rank a name against the universe), not the index GEX/RND structure. Each factor emits the
same explainable ``FactorSignal`` the option factors do, so equity tips reuse the entire
Tip → ledger → validation spine unchanged. Inputs are a plain daily-close series (+ optional futures
OI), so the whole path is chain-free and cheap.

Edge tiers reflect the published evidence: 12-1 price momentum is the most-replicated single-name
cross-sectional anomaly (STRONG); short-horizon reversal and futures OI-buildup are CONFIRMATION /
contextual. None of these promise accuracy — conviction is calibrated by the ledger like every tip.
"""

from __future__ import annotations

import math

from ..strategy.types import BEARISH, BULLISH
from .base import CONFIRMATION, STRONG, FactorSignal

MOMENTUM = "equity_momentum_12_1"
REVERSAL = "equity_reversal_1w"
OI_BUILDUP = "equity_oi_buildup"


def _ret(a: float, b: float) -> float:
    return (b / a - 1.0) if (a and a > 0) else 0.0


def momentum_12_1(prices: list[float]) -> FactorSignal:
    """~12-day price momentum, skipping the most recent day (avoids the 1-day reversal). Needs ≥14
    closes. The classic cross-sectional anomaly: recent relative winners tend to keep winning over a
    ~1-4 week horizon."""
    if len(prices) < 14:
        return FactorSignal(MOMENTUM, False, 0.0, "", STRONG, {"reason": "insufficient_history"})
    r = _ret(prices[-13], prices[-2])  # 12 trading days back → yesterday
    if r >= 0.02:
        direction, fired = BULLISH, True
    elif r <= -0.02:
        direction, fired = BEARISH, True
    else:
        direction, fired = "", False
    strength = round(min(1.0, abs(r) / 0.12), 3) if fired else 0.0
    return FactorSignal(MOMENTUM, fired, strength, direction, STRONG, {"ret_12_1": round(r, 4)})


def reversal_1w(prices: list[float]) -> FactorSignal:
    """1-week z-score reversal: fade an abnormally large most-recent daily move. CONFIRMATION-only
    (weak, contextual) — it tempers, never headlines."""
    if len(prices) < 21:
        return FactorSignal(REVERSAL, False, 0.0, "", CONFIRMATION, {"reason": "insufficient_history"})
    window = prices[-21:]
    rets = [_ret(window[i - 1], window[i]) for i in range(1, len(window))]
    mean = sum(rets) / len(rets)
    var = sum((x - mean) ** 2 for x in rets) / max(1, len(rets) - 1)
    sd = math.sqrt(var)
    z = (rets[-1] - mean) / sd if sd > 0 else 0.0
    if z >= 1.5:
        direction, fired = BEARISH, True   # sharp up day → fade
    elif z <= -1.5:
        direction, fired = BULLISH, True   # sharp down day → bounce
    else:
        direction, fired = "", False
    strength = round(min(1.0, abs(z) / 3.0), 3) if fired else 0.0
    return FactorSignal(REVERSAL, fired, strength, direction, CONFIRMATION, {"z": round(z, 3)})


def oi_buildup(price_change_pct: float, oi: float, oi_change: float) -> FactorSignal:
    """Futures OI buildup read: price↑ & OI↑ = long buildup (bullish); price↓ & OI↑ = short buildup
    (bearish); price↑ & OI↓ = short covering (bullish); price↓ & OI↓ = long unwinding (bearish).
    Strength scales with the relative OI change."""
    if oi_change == 0 or oi <= 0:
        return FactorSignal(OI_BUILDUP, False, 0.0, "", STRONG, {"reason": "no_oi_change"})
    up_p, up_oi = price_change_pct > 0, oi_change > 0
    if up_p and up_oi:
        direction, label = BULLISH, "long_buildup"
    elif (not up_p) and up_oi:
        direction, label = BEARISH, "short_buildup"
    elif up_p and not up_oi:
        direction, label = BULLISH, "short_covering"
    else:
        direction, label = BEARISH, "long_unwinding"
    prev_oi = max(1.0, oi - oi_change)
    strength = round(min(1.0, abs(oi_change) / prev_oi), 3)
    return FactorSignal(OI_BUILDUP, True, strength, direction, STRONG,
                        {"label": label, "oi_change": oi_change, "oi": oi})


def equity_signals(
    prices: list[float], *, oi: float | None = None, oi_change: float | None = None
) -> list[FactorSignal]:
    """All single-stock factors for one name. ``prices`` is the ascending daily-close series up to
    (and including) the as-of day; ``oi``/``oi_change`` are the stock-future OI when available."""
    sigs = [momentum_12_1(prices), reversal_1w(prices)]
    if oi is not None and oi_change is not None and len(prices) >= 2:
        pct = _ret(prices[-2], prices[-1])
        sigs.append(oi_buildup(pct, oi, oi_change))
    return sigs
