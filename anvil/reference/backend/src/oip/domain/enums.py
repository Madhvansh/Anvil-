"""Enumerations used across the domain.

`OptionType` values are the single-character flags the Black-76 engine expects ("c"/"p"), so the
same value flows from the chain through the engine without translation. These are `StrEnum`s, so
members compare/serialize as their string value.
"""

from __future__ import annotations

from enum import StrEnum


class OptionType(StrEnum):
    CALL = "c"
    PUT = "p"

    @property
    def is_call(self) -> bool:
        return self is OptionType.CALL


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"


class FuturePriceSource(StrEnum):
    """How `OptionChain.future_price` was obtained — kept auditable per ADR 0005.

    Black-76 requires the futures price, but NSE's chain payload only carries spot, so a
    short-dated cost-of-carry forward may be derived. The source is recorded so a Greek computed
    from a derived forward is never mistaken for one computed from a real future.
    """

    NSE_FUTURES = "nse_futures"
    DERIVED_COST_OF_CARRY = "derived_cost_of_carry"
    KITE = "kite"
    FIXTURE = "fixture"
