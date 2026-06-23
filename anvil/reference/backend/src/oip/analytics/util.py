"""Shared helpers for the analytics modules.

Time-to-expiry, ATM strike (relative to the FUTURE, not spot), and the effective IV for a leg
(reported IV if present, else backed out from the last price via the Black-76 engine).
"""

from __future__ import annotations

from ..domain.models import OptionChain, OptionQuote
from ..quant import black76
from ..quant.greeks_service import year_fraction


def chain_t_years(chain: OptionChain) -> float:
    """ACT/365 years to the chain's (single) expiry. 0.0 if the chain is empty."""
    if not chain.rows:
        return 0.0
    return year_fraction(chain.snapshot_ts, chain.rows[0].expiry)


def atm_strike(chain: OptionChain) -> float:
    """Strike nearest the FUTURES price (the Black-76 forward), not spot."""
    strikes = [r.strike for r in chain.rows]
    if not strikes:
        return chain.future_price
    return min(strikes, key=lambda k: abs(k - chain.future_price))


def effective_iv(
    quote: OptionQuote | None, F: float, K: float, t: float, r: float
) -> float | None:
    """Reported IV if usable, else implied from the last price; None if neither works."""
    if quote is None:
        return None
    if quote.iv_source is not None and quote.iv_source > 0:
        return quote.iv_source
    if quote.last_price is not None and quote.last_price > 0 and t > 0:
        try:
            iv = black76.implied_vol(quote.option_type, quote.last_price, F, K, t, r)
        except ValueError:
            return None
        return iv if (iv == iv and iv > 0) else None  # filter NaN
    return None
