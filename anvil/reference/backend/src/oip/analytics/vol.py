"""IV / volatility context: ATM IV, the IV smile, a simple skew measure, and IV rank/percentile.

ATM is measured relative to the FUTURE. Term structure and IV rank need history across snapshots;
`iv_rank`/`iv_percentile` take a history list (pulled from the snapshot store by the caller) and
return None when there isn't enough history to be meaningful.
"""

from __future__ import annotations

from ..domain.models import OptionChain
from .util import atm_strike, chain_t_years, effective_iv


def iv_smile(chain: OptionChain) -> list[tuple[float, float | None, float | None]]:
    """(strike, call_iv, put_iv) sorted by strike, using effective IVs."""
    F, r, t = chain.future_price, chain.risk_free_rate, chain_t_years(chain)
    out = []
    for row in sorted(chain.rows, key=lambda x: x.strike):
        out.append(
            (
                row.strike,
                effective_iv(row.call, F, row.strike, t, r),
                effective_iv(row.put, F, row.strike, t, r),
            )
        )
    return out


def atm_iv(chain: OptionChain) -> float | None:
    """Average of the call and put effective IV at the ATM strike."""
    F, r, t = chain.future_price, chain.risk_free_rate, chain_t_years(chain)
    k = atm_strike(chain)
    row = next((x for x in chain.rows if x.strike == k), None)
    if row is None:
        return None
    vals = [
        v
        for v in (
            effective_iv(row.call, F, k, t, r),
            effective_iv(row.put, F, k, t, r),
        )
        if v is not None
    ]
    return sum(vals) / len(vals) if vals else None


def skew(chain: OptionChain, wing_pct: float = 0.05) -> float | None:
    """Simple put-vs-call skew: (OTM put IV) − (OTM call IV) at ~wing_pct from the future.

    Positive => downside (put) protection is richer than upside — the usual equity-index skew.
    """
    F, r, t = chain.future_price, chain.risk_free_rate, chain_t_years(chain)
    rows = sorted(chain.rows, key=lambda x: x.strike)
    if not rows:
        return None
    put_row = min(rows, key=lambda x: abs(x.strike - F * (1 - wing_pct)))
    call_row = min(rows, key=lambda x: abs(x.strike - F * (1 + wing_pct)))
    piv = effective_iv(put_row.put, F, put_row.strike, t, r)
    civ = effective_iv(call_row.call, F, call_row.strike, t, r)
    if piv is None or civ is None:
        return None
    return piv - civ


def iv_rank(current_iv: float | None, history: list[float | None]) -> float | None:
    """Where current IV sits in [min, max] of history, in [0, 1]. None if history is too thin."""
    hist = [h for h in history if h is not None]
    if current_iv is None or len(hist) < 2:
        return None
    lo, hi = min(hist), max(hist)
    if hi == lo:
        return None
    return max(0.0, min(1.0, (current_iv - lo) / (hi - lo)))


def iv_percentile(current_iv: float | None, history: list[float | None]) -> float | None:
    """Fraction of history strictly below current IV. None if history is too thin."""
    hist = [h for h in history if h is not None]
    if current_iv is None or not hist:
        return None
    return sum(1 for h in hist if h < current_iv) / len(hist)
