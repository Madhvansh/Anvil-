"""In-memory simulator state — plain dataclasses shared by the gateway, MTM, and account.

These are the runtime projection. The async-SQLAlchemy ``paper_*`` tables (db/models.py) persist
snapshots of them via paper/repo.py; the deterministic replay + report can run entirely on these
in memory (no DB, no keys), which is what the test suite exercises.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..engine.util import json_safe
from ..models import OptionType


@dataclass
class Fill:
    ts: str
    symbol: str
    underlying: str
    side: str  # BUY | SELL
    lots: int
    qty: int  # absolute contract qty (lots * lot_size)
    fill_price: float
    ref_mid: float
    slippage: float
    charges: dict  # costs.Charges.as_dict()
    kind: str  # open | close
    instrument_type: str = "CE"
    strike: float | None = None
    expiry: str | None = None
    option_type: str | None = None
    status: str = "FILLED_SIMULATED"

    def as_dict(self) -> dict:
        return json_safe(self.__dict__)


@dataclass
class PaperLeg:
    side: str
    lots: int
    instrument_type: str  # CE | PE | FUT | EQ
    expiry: str
    entry_price: float  # actual open fill price
    option_type: OptionType | None = None
    strike: float | None = None
    symbol: str | None = None

    @property
    def sign(self) -> int:
        return 1 if str(self.side).upper() == "BUY" else -1

    def qty(self, lot_size: int) -> int:
        return int(self.lots) * int(lot_size)

    def as_dict(self) -> dict:
        return json_safe(
            {
                "side": self.side,
                "lots": self.lots,
                "instrument_type": self.instrument_type,
                "expiry": self.expiry,
                "entry_price": self.entry_price,
                "option_type": self.option_type.value if self.option_type else None,
                "strike": self.strike,
                "symbol": self.symbol,
            }
        )


@dataclass
class PaperPosition:
    id: int
    underlying: str
    strategy: str
    direction: str
    opened_at: str
    lot_size: int
    legs: list[PaperLeg]
    entry_value: float  # net debit at open (positive = paid, negative = credit received), from fills
    max_loss: float
    max_profit: float | None
    reserved_margin: float
    conviction: float
    edge_prob: float
    opened_regime: str
    exit_rules: dict = field(default_factory=dict)
    status: str = "open"
    closed_at: str | None = None
    close_reason: str | None = None
    mark_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    charges_paid: float = 0.0
    mae: float = 0.0  # max adverse excursion (most negative unrealized seen)
    mfe: float = 0.0  # max favorable excursion (most positive unrealized seen)
    greeks: dict = field(default_factory=dict)
    recommendation: dict = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)
    ledger_forecast_id: str | None = None

    def as_dict(self) -> dict:
        return json_safe(
            {
                "id": self.id,
                "underlying": self.underlying,
                "strategy": self.strategy,
                "direction": self.direction,
                "opened_at": self.opened_at,
                "closed_at": self.closed_at,
                "status": self.status,
                "lot_size": self.lot_size,
                "legs": [leg.as_dict() for leg in self.legs],
                "entry_value": self.entry_value,
                "max_loss": self.max_loss,
                "max_profit": self.max_profit,
                "reserved_margin": self.reserved_margin,
                "conviction": self.conviction,
                "edge_prob": self.edge_prob,
                "opened_regime": self.opened_regime,
                "exit_rules": self.exit_rules,
                "mark_value": self.mark_value,
                "unrealized_pnl": self.unrealized_pnl,
                "realized_pnl": self.realized_pnl,
                "charges_paid": self.charges_paid,
                "mae": self.mae,
                "mfe": self.mfe,
                "greeks": self.greeks,
                "close_reason": self.close_reason,
                "ledger_forecast_id": self.ledger_forecast_id,
            }
        )


@dataclass
class EquityPoint:
    ts: str
    equity: float
    cash: float
    unrealized_pnl: float
    realized_pnl: float
    gross_exposure: float
    net_delta: float
    open_positions: int
    drawdown: float

    def as_dict(self) -> dict:
        return json_safe(self.__dict__)
