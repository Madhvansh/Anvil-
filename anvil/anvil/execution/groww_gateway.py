"""Groww order gateway — the real broker adapter, gated for safety.

`dry_run=True` (the default) validates and logs the order but NEVER calls the broker — it
returns a SIMULATED ticket. Only when `dry_run=False` (the CLI `--live` path) does it hit
`growwapi.place_order`. All orders still flow through the assisted/gated executor; auto-exec
stays OFF. Selling demat holdings additionally requires DDPI/TPIN on the account.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .gateway import OrderGateway, OrderRequest, OrderTicket


class GrowwOrderGateway(OrderGateway):
    def __init__(self, client=None, dry_run: bool = True):
        self.dry_run = dry_run
        self._client = client

    @property
    def groww(self):
        if self._client is None:
            from ..ingest.groww import _make_client

            self._client = _make_client()
        return self._client

    def place(self, req: OrderRequest) -> OrderTicket:
        ts = datetime.now(timezone.utc).isoformat()
        if self.dry_run:
            return OrderTicket(
                request=req, status="SIMULATED", created_at=ts,
                note="dry-run: validated and logged, NOT sent to the broker (pass --live to arm)",
            )
        g = self.groww
        resp = g.place_order(
            trading_symbol=req.symbol,
            quantity=int(req.quantity),
            validity=g.VALIDITY_DAY,
            exchange=getattr(g, f"EXCHANGE_{req.exchange}"),
            segment=getattr(g, f"SEGMENT_{req.segment}"),
            product=getattr(g, f"PRODUCT_{req.product}"),
            order_type=getattr(g, f"ORDER_TYPE_{req.order_type}"),
            transaction_type=getattr(g, f"TRANSACTION_TYPE_{req.side}"),
            price=req.price,
        )
        oid = resp.get("groww_order_id") if isinstance(resp, dict) else None
        return OrderTicket(request=req, status="PLACED", created_at=ts, broker_order_id=oid, note="placed via Groww")
