"""The as-of guard layer — the bias controls that make the backtest trustworthy.

Every read for a forecast goes through an ``AsOfContext`` pinned to a single trading day. It
*raises* (fails the build, via the test suite) on look-ahead, and it *excludes* contracts that
never traded (survivorship). These are not warnings — a violation is an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from ..models import OptionChain

if TYPE_CHECKING:  # avoid a runtime import cycle
    from .data import BhavcopyArchive


class LookAheadError(AssertionError):
    """Raised when a forecast would use information not available on its as-of day."""


class SurvivorshipError(AssertionError):
    """Raised when a never-traded contract is forced into a forecast."""


def _date(ts: str) -> str:
    return (ts or "")[:10]


def filter_liquid(chain: OptionChain) -> OptionChain:
    """Keep only contracts that actually traded (OI or volume > 0) on the as-of day."""
    live = [r for r in chain.rows if (r.oi or 0) > 0 or (r.volume or 0) > 0]
    return chain.model_copy(update={"rows": live})


def assert_all_liquid(chain: OptionChain) -> None:
    dead = [r.strike for r in chain.rows if not ((r.oi or 0) > 0 or (r.volume or 0) > 0)]
    if dead:
        raise SurvivorshipError(f"{chain.underlying} {chain.expiry}: never-traded strikes {dead}")


@dataclass
class AsOfContext:
    asof: date
    archive: "BhavcopyArchive"

    def open_chains(self, underlying: str) -> list[OptionChain]:
        """Live, liquid chains for ``underlying`` as of this day. Raises on any look-ahead."""
        today = self.asof.isoformat()
        out: list[OptionChain] = []
        for ch in self.archive.chains_on(self.asof):
            if ch.underlying != underlying.upper():
                continue
            if _date(ch.timestamp) != today:  # point-in-time: the chain must BE this day's
                raise LookAheadError(f"chain timestamp {ch.timestamp!r} != as-of {today}")
            if ch.expiry and ch.expiry <= today:  # cannot forecast an already-settled expiry
                raise LookAheadError(f"expiry {ch.expiry!r} is not after as-of {today}")
            out.append(filter_liquid(ch))
        return out

    def realized_level(self, underlying: str) -> float | None:
        """The realized cash close for ``underlying`` on this day (the settlement level)."""
        return self.archive.index_close_on(self.asof, underlying)
