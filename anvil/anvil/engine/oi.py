"""Open-Interest analytics: buildup classification, PCR, max pain, OI walls."""

from __future__ import annotations

from dataclasses import dataclass

from ..models import OptionChain


def classify_buildup(price_change: float, oi_change: float) -> str:
    """The classic OI x price matrix.

    price up + OI up   -> long buildup       (fresh longs, bullish)
    price down + OI up -> short buildup      (fresh shorts, bearish)
    price up + OI down -> short covering     (shorts exiting, bullish)
    price down + OI down-> long unwinding    (longs exiting, bearish)
    """
    p, o = price_change, oi_change
    if p >= 0 and o >= 0:
        return "long_buildup"
    if p < 0 and o >= 0:
        return "short_buildup"
    if p >= 0 and o < 0:
        return "short_covering"
    return "long_unwinding"


def pcr_oi(chain: OptionChain) -> float | None:
    call_oi = sum(r.oi for r in chain.calls())
    put_oi = sum(r.oi for r in chain.puts())
    return (put_oi / call_oi) if call_oi else None


def pcr_volume(chain: OptionChain) -> float | None:
    call_v = sum(r.volume for r in chain.calls())
    put_v = sum(r.volume for r in chain.puts())
    return (put_v / call_v) if call_v else None


def max_pain(chain: OptionChain) -> float | None:
    """Strike at which total option-writer payout (intrinsic value owed) is minimized."""
    strikes = chain.strikes()
    if not strikes:
        return None
    call_oi = {r.strike: r.oi for r in chain.calls()}
    put_oi = {r.strike: r.oi for r in chain.puts()}

    best_strike, best_pain = None, None
    for expiry_price in strikes:
        pain = 0.0
        for k in strikes:
            pain += max(expiry_price - k, 0.0) * call_oi.get(k, 0.0)  # ITM calls
            pain += max(k - expiry_price, 0.0) * put_oi.get(k, 0.0)  # ITM puts
        if best_pain is None or pain < best_pain:
            best_pain, best_strike = pain, expiry_price
    return best_strike


@dataclass
class OIWalls:
    call_resistance: list[tuple[float, float]]  # (strike, oi), descending
    put_support: list[tuple[float, float]]


def oi_walls(chain: OptionChain, n: int = 3) -> OIWalls:
    """Highest-OI call strikes act as resistance; highest-OI put strikes as support."""
    calls = sorted(((r.strike, r.oi) for r in chain.calls()), key=lambda x: x[1], reverse=True)
    puts = sorted(((r.strike, r.oi) for r in chain.puts()), key=lambda x: x[1], reverse=True)
    return OIWalls(call_resistance=calls[:n], put_support=puts[:n])


def total_oi_change(chain: OptionChain) -> dict[str, float]:
    return {
        "call": sum(r.oi_change for r in chain.calls()),
        "put": sum(r.oi_change for r in chain.puts()),
    }
