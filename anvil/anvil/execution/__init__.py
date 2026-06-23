"""Execution layer — a pluggable seam, gated for compliance.

`AssistedExecutor` (user confirms every order) is allowed now. `AutoExecutor`
(programmatic placement) is built but **gated** behind ``SETTINGS.trading_automation``,
which defaults OFF and must stay OFF until SEBI algo empanelment (broker registration,
exchange-issued algo IDs, audit trail) is in place. This keeps the order code ready
without ever silently trading.
"""

from .gateway import (
    AssistedExecutor,
    AutoExecutor,
    OrderGateway,
    OrderRequest,
    TradingDisabledError,
    get_executor,
)

__all__ = [
    "OrderGateway",
    "OrderRequest",
    "AssistedExecutor",
    "AutoExecutor",
    "TradingDisabledError",
    "get_executor",
]
