"""Open-interest analytics: PCR, max pain, OI walls, and OI×price buildup classification.

These are positioning statistics, not Greeks — they read OI/volume off the chain and need no
pricing model.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.models import OptionChain


def _call_oi(chain: OptionChain) -> dict[float, float]:
    return {r.strike: (r.call.oi or 0.0) for r in chain.rows if r.call}


def _put_oi(chain: OptionChain) -> dict[float, float]:
    return {r.strike: (r.put.oi or 0.0) for r in chain.rows if r.put}


def pcr_oi(chain: OptionChain) -> float | None:
    call = sum(_call_oi(chain).values())
    put = sum(_put_oi(chain).values())
    return (put / call) if call else None


def pcr_volume(chain: OptionChain) -> float | None:
    call = sum((r.call.volume or 0.0) for r in chain.rows if r.call)
    put = sum((r.put.volume or 0.0) for r in chain.rows if r.put)
    return (put / call) if call else None


def max_pain(chain: OptionChain) -> float | None:
    """Strike at which total option-writer payout (intrinsic owed) is minimized at expiry."""
    strikes = sorted({r.strike for r in chain.rows})
    if not strikes:
        return None
    call_oi, put_oi = _call_oi(chain), _put_oi(chain)
    best_strike: float | None = None
    best_pain: float | None = None
    for expiry_price in strikes:
        pain = 0.0
        for k in strikes:
            pain += max(expiry_price - k, 0.0) * call_oi.get(k, 0.0)  # ITM calls owed
            pain += max(k - expiry_price, 0.0) * put_oi.get(k, 0.0)  # ITM puts owed
        if best_pain is None or pain < best_pain:
            best_pain, best_strike = pain, expiry_price
    return best_strike


@dataclass
class OIWalls:
    call_resistance: list[tuple[float, float]]  # (strike, oi), descending
    put_support: list[tuple[float, float]]


def oi_walls(chain: OptionChain, n: int = 3) -> OIWalls:
    """Highest-OI call strikes act as resistance; highest-OI put strikes as support."""
    calls = sorted(_call_oi(chain).items(), key=lambda kv: kv[1], reverse=True)
    puts = sorted(_put_oi(chain).items(), key=lambda kv: kv[1], reverse=True)
    return OIWalls(call_resistance=calls[:n], put_support=puts[:n])


def classify_buildup(price_change: float, oi_change: float) -> str:
    """The classic OI × price matrix.

    price up + OI up     -> long_buildup    (fresh longs, bullish)
    price down + OI up   -> short_buildup   (fresh shorts, bearish)
    price up + OI down   -> short_covering  (shorts exiting, bullish)
    price down + OI down -> long_unwinding  (longs exiting, bearish)
    """
    if price_change >= 0 and oi_change >= 0:
        return "long_buildup"
    if price_change < 0 and oi_change >= 0:
        return "short_buildup"
    if price_change >= 0 and oi_change < 0:
        return "short_covering"
    return "long_unwinding"
