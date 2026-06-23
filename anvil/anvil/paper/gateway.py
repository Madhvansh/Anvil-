"""PaperBrokerGateway — simulated fills off live bid/ask, never touching a broker.

Implements the existing ``OrderGateway`` seam so paper orders flow through ``AssistedExecutor``
exactly like real ones would (the real path stays gated behind ``AutoExecutor`` /
``TRADING_AUTOMATION``). Fills cross the quoted spread (or apply slippage), and the full India F&O
charge stack is attached. The gateway NEVER makes a network call.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..execution.gateway import OrderGateway, OrderRequest, OrderTicket
from . import costs
from .state import Fill


class PaperBrokerGateway(OrderGateway):
    """A mock fill engine. ``mark_fn(symbol) -> (mid, bid, ask)`` supplies the live quote."""

    def __init__(self, mark_fn=None, brokerage_per_order: float | None = None):
        self.mark_fn = mark_fn
        self.brokerage_per_order = brokerage_per_order

    def simulate_fill(
        self,
        *,
        side: str,
        qty: int,
        lots: int,
        mid: float,
        bid: float | None,
        ask: float | None,
        instrument_type: str,
        underlying: str,
        symbol: str,
        ts: str | None = None,
        kind: str = "open",
        strike: float | None = None,
        expiry: str | None = None,
        option_type: str | None = None,
    ) -> Fill:
        """Core simulator entry: price one leg, attach charges, return a Fill. No network."""
        ts = ts or datetime.now(timezone.utc).isoformat()
        price = costs.fill_price(side, mid, bid, ask)
        chg = costs.charges(side, price, qty, instrument_type, self.brokerage_per_order)
        return Fill(
            ts=ts,
            symbol=symbol,
            underlying=underlying,
            side=side.upper(),
            lots=int(lots),
            qty=int(qty),
            fill_price=round(float(price), 4),
            ref_mid=round(float(mid), 4),
            slippage=round(float(price - mid), 4),
            charges=chg.as_dict(),
            kind=kind,
            instrument_type=instrument_type,
            strike=strike,
            expiry=expiry,
            option_type=option_type,
        )

    def place(self, req: OrderRequest) -> OrderTicket:
        """OrderGateway-compatible single-order path (used via AssistedExecutor for paper orders)."""
        ts = datetime.now(timezone.utc).isoformat()
        mid, bid, ask = (None, None, None)
        if self.mark_fn is not None:
            mid, bid, ask = self.mark_fn(req.symbol)
        if not mid or mid <= 0:
            return OrderTicket(request=req, status="BLOCKED", created_at=ts, note="paper: no live mark for symbol")
        fill = self.simulate_fill(
            side=req.side, qty=int(req.quantity), lots=int(req.quantity), mid=mid, bid=bid, ask=ask,
            instrument_type=req.segment if req.segment in ("FUT", "EQ") else "CE",
            underlying=req.symbol, symbol=req.symbol, ts=ts, kind="open",
        )
        return OrderTicket(
            request=req,
            status="FILLED_SIMULATED",
            created_at=ts,
            note=f"paper fill @ {fill.fill_price} (charges {fill.charges['total']})",
            broker_order_id=f"PAPER-{abs(hash((req.symbol, ts))) % 10_000_000}",
        )
