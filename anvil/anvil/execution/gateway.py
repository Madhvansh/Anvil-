"""Order gateway interface + assisted (now) and auto (gated) executors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from ..config import SETTINGS


class TradingDisabledError(RuntimeError):
    """Raised when automated execution is attempted while the gate is OFF."""


@dataclass
class OrderRequest:
    symbol: str
    side: str  # "BUY" | "SELL"
    quantity: int
    order_type: str = "LIMIT"  # "MARKET" | "LIMIT" | "STOP_LOSS" | "STOP_LOSS_MARKET"
    price: float | None = None
    product: str = "NRML"  # "NRML" | "MIS" | "CNC"
    exchange: str = "NSE"  # "NSE" | "BSE"
    segment: str = "FNO"  # "FNO" | "CASH"
    rationale: str = ""  # why the engine suggested this (for the audit log)


@dataclass
class OrderTicket:
    request: OrderRequest
    status: str  # "PENDING_USER_CONFIRMATION" | "PLACED" | "BLOCKED"
    created_at: str
    note: str = ""
    broker_order_id: str | None = None


class OrderGateway:
    """Interface a broker adapter implements to actually place orders."""

    def place(self, req: OrderRequest) -> OrderTicket:  # pragma: no cover - adapter
        raise NotImplementedError


@dataclass
class AssistedExecutor:
    """Default-safe: never places an order itself. Produces a confirmable ticket the
    user (or UI) must approve, then hands to a broker gateway on explicit confirm.
    """

    gateway: OrderGateway | None = None
    audit: list[OrderTicket] = field(default_factory=list)

    def propose(self, req: OrderRequest) -> OrderTicket:
        ticket = OrderTicket(
            request=req,
            status="PENDING_USER_CONFIRMATION",
            created_at=datetime.now(timezone.utc).isoformat(),
            note="Assisted mode — requires explicit user confirmation before placement.",
        )
        self.audit.append(ticket)
        return ticket

    def confirm(self, ticket: OrderTicket) -> OrderTicket:
        if ticket.status != "PENDING_USER_CONFIRMATION":
            raise ValueError("Ticket is not awaiting confirmation.")
        if self.gateway is None:
            ticket.status = "BLOCKED"
            ticket.note = "No broker gateway configured."
            return ticket
        placed = self.gateway.place(ticket.request)
        self.audit.append(placed)
        return placed


@dataclass
class AutoExecutor:
    """Programmatic placement — GATED. Refuses to act unless TRADING_AUTOMATION is on
    AND a gateway is configured. Building it now keeps the seam ready for later.
    """

    gateway: OrderGateway | None = None
    audit: list[OrderTicket] = field(default_factory=list)

    def place(self, req: OrderRequest) -> OrderTicket:
        if not SETTINGS.trading_automation:
            raise TradingDisabledError(
                "Automated execution is OFF (TRADING_AUTOMATION=false). Requires SEBI algo "
                "empanelment (broker registration, exchange algo IDs, audit trail) before enabling."
            )
        if self.gateway is None:
            raise TradingDisabledError("No broker gateway configured.")
        placed = self.gateway.place(req)
        self.audit.append(placed)
        return placed


def get_executor(gateway: OrderGateway | None = None):
    """Return the appropriate executor for the current gate state."""
    if SETTINGS.trading_automation:
        return AutoExecutor(gateway=gateway)
    return AssistedExecutor(gateway=gateway)
