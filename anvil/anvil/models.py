"""Normalized data schemas shared across ingestion, engine, store, and API.

These are source-agnostic: every connector (Upstox/Dhan/Kite/demo) maps its raw
payload into these types so the engine never sees vendor-specific shapes.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class OptionType(str, Enum):
    CALL = "CE"
    PUT = "PE"


class Greeks(BaseModel):
    """Per-contract Greeks.

    Conventions: ``theta`` and ``charm`` are per calendar day; ``vega`` is per
    1 percentage-point change in IV; ``rho`` is per 1 percentage-point change in
    the rate. ``delta``/``gamma`` are per ₹1 move in the underlying.
    """

    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float
    vanna: float | None = None
    charm: float | None = None
    vomma: float | None = None


class ChainRow(BaseModel):
    strike: float
    option_type: OptionType
    ltp: float | None = None
    bid: float | None = None
    ask: float | None = None
    oi: float = 0.0
    oi_change: float = 0.0
    volume: float = 0.0
    iv: float | None = None  # decimal, e.g. 0.15 == 15%
    greeks: Greeks | None = None


class OptionChain(BaseModel):
    underlying: str
    spot: float
    expiry: str  # ISO date, e.g. "2026-06-25"
    timestamp: str  # ISO datetime
    rows: list[ChainRow] = Field(default_factory=list)
    future_price: float | None = None
    # Provenance of the forward used for Black-76 pricing: e.g. "nse_futures",
    # "provided", "fixture", "derived_cost_of_carry". Never silently mis-source a Greek.
    future_price_source: str | None = None
    vix: float | None = None
    lot_size: int = 1
    # Optional EOD context (filled by nse_eod connector)
    underlying_prev_close: float | None = None

    def calls(self) -> list[ChainRow]:
        return [r for r in self.rows if r.option_type == OptionType.CALL]

    def puts(self) -> list[ChainRow]:
        return [r for r in self.rows if r.option_type == OptionType.PUT]

    def strikes(self) -> list[float]:
        return sorted({r.strike for r in self.rows})

    def atm_strike(self) -> float:
        ks = self.strikes()
        return min(ks, key=lambda k: abs(k - self.spot)) if ks else self.spot

    def row(self, strike: float, option_type: OptionType) -> ChainRow | None:
        for r in self.rows:
            if r.strike == strike and r.option_type == option_type:
                return r
        return None


class Position(BaseModel):
    """A single holding/position, normalized across brokers."""

    symbol: str
    underlying: str
    instrument_type: str  # "EQ" | "FUT" | "CE" | "PE"
    quantity: float = 0.0  # signed, in units (shares); F&O already * lot size
    lot_size: int = 1
    avg_price: float = 0.0
    ltp: float = 0.0
    strike: float | None = None
    option_type: OptionType | None = None
    expiry: str | None = None  # ISO date
    underlying_price: float | None = None
    iv: float | None = None  # decimal
    beta: float = 1.0  # vs benchmark index


class Bar(BaseModel):
    """One OHLCV(+OI) bar at a given timeframe — the unit of the multi-timeframe momentum store.

    ``tf`` is a timeframe label ("1m", "5m", "15m", "1h", "1d", "1w"); ``ts`` is the bar's OPEN time
    as an ISO string (IST-aware preferred). ``symbol`` is the underlying/equity name (index name or
    NSE symbol), source-agnostic like the rest of ``anvil.models``.
    """

    symbol: str
    tf: str
    ts: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    oi: float | None = None


class Snapshot(BaseModel):
    """A computed analytics snapshot — the unit stored in the time-series moat."""

    underlying: str
    timestamp: str
    spot: float
    expiry: str
    pcr_oi: float | None = None
    pcr_volume: float | None = None
    max_pain: float | None = None
    total_gex: float | None = None
    zero_gamma_flip: float | None = None
    expected_move_1sigma: float | None = None
    atm_iv: float | None = None
    regime: str | None = None
    extra: dict = Field(default_factory=dict)
