"""Connector interface — the contract every data source implements."""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import OptionChain, Position


def attach_parity_forward(chain: OptionChain) -> OptionChain:
    """Ensure a live chain carries a real forward for Black-76. If the source didn't supply a
    future price, recover the market forward from put-call parity at the ATM strike and tag it
    ``put_call_parity`` — so Greeks are never silently priced off a cost-of-carry guess."""
    if chain.future_price and chain.future_price > 0:
        return chain
    from ..engine.forward import forward_from_parity

    fwd = forward_from_parity(chain)
    if fwd:
        return chain.model_copy(update={"future_price": fwd, "future_price_source": "put_call_parity"})
    return chain


class Connector(ABC):
    """Source-agnostic market-data + positions interface.

    Implementations normalize their vendor payloads into anvil.models types so the
    engine never sees vendor-specific shapes. Market data and positions can come
    from *different* connectors (e.g. Upstox for chains, Kite for positions).
    """

    name: str = "base"
    provides_chain: bool = False
    provides_positions: bool = False

    @abstractmethod
    def get_chain(self, underlying: str, expiry: str | None = None) -> OptionChain:
        """Return the option chain (with OI; IV/Greeks if the source provides them)."""

    def get_expiries(self, underlying: str) -> list[str]:  # pragma: no cover - optional
        raise NotImplementedError

    def get_positions(self) -> list[Position]:  # pragma: no cover - optional
        raise NotImplementedError

    def get_historical_candles(
        self, underlying: str, interval_min: int = 15, start: str | None = None, end: str | None = None
    ) -> list[tuple[str, float, float, float, float]]:  # pragma: no cover - optional
        """Real intraday OHLC for the underlying: [(iso_ts, open, high, low, close), ...]. Used to
        replay a real trading day. Not every source provides it (raise to signal that)."""
        raise NotImplementedError

    def close(self) -> None:  # pragma: no cover - optional
        pass
