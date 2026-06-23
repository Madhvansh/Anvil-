"""Resolve the forward/futures price used by the Black-76 engine — and tag its source.

A Greek is never silently computed off the wrong underlying: if the chain carries a traded
future, we use it (tagged); otherwise we derive a cost-of-carry forward F = S·e^{(r−q)T} and
tag it ``derived_cost_of_carry`` so downstream consumers and the calibration ledger know
exactly what the number was based on.
"""

from __future__ import annotations

import math

from ..config import SETTINGS
from ..models import OptionChain, OptionType
from .util import year_fraction


def resolve_forward(chain: OptionChain, r: float | None = None, q: float | None = None) -> tuple[float, str]:
    """Return (forward_price, source_tag)."""
    r = SETTINGS.risk_free_rate if r is None else r
    q = SETTINGS.dividend_yield if q is None else q
    if chain.future_price and chain.future_price > 0:
        return float(chain.future_price), (chain.future_price_source or "provided")
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-9)
    return float(chain.spot * math.exp((r - q) * T)), "derived_cost_of_carry"


def forward_from_parity(chain: OptionChain, r: float | None = None) -> float | None:
    """Market-implied forward from put-call parity at the ATM strike:
    ``F = K + e^{rT}·(C − P)``. This recovers the *traded* forward straight from the option
    prices (no separate futures fetch, and more honest than a cost-of-carry guess) — live
    connectors use it to feed Black-76 a real forward (tagged ``put_call_parity``).
    Returns None if the ATM call/put aren't both quoted."""
    r = SETTINGS.risk_free_rate if r is None else r
    atm = chain.atm_strike()
    c = chain.row(atm, OptionType.CALL)
    p = chain.row(atm, OptionType.PUT)
    if not (c and p and c.ltp and p.ltp and c.ltp > 0 and p.ltp > 0):
        return None
    T = max(year_fraction(chain.expiry, chain.timestamp), 1e-9)
    fwd = float(atm) + math.exp(r * T) * (float(c.ltp) - float(p.ltp))
    return fwd if fwd > 0 else None
