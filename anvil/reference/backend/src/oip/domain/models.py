"""Core domain models.

These are the internal, normalized representations the whole platform speaks. Raw NSE/broker
payloads are converted into these by the data layer; the API serializes views of them.

Unit conventions for `GreeksResult` (presentation units — see ADR 0004):
- delta, gamma: dimensionless (per 1 unit of futures price for gamma's denominator).
- theta_per_day: option price change per CALENDAR day (raw per-year theta / 365).
- vega_per_pct: option price change per 1 percentage-point (0.01) change in IV.
- rho: option price change per 1 percentage-point change in the rate (raw per-1.0 rho / 100).
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field

from .enums import Exchange, FuturePriceSource, OptionType


class OptionQuote(BaseModel):
    """One side (call or put) of a strike, as reported by the source."""

    model_config = ConfigDict(frozen=True)

    option_type: OptionType
    last_price: float | None = None
    bid: float | None = None
    ask: float | None = None
    oi: int | None = None
    volume: int | None = None
    iv_source: float | None = Field(
        default=None,
        description="Implied volatility as reported by the source, as a DECIMAL (0.12 = 12%).",
    )


class ChainRow(BaseModel):
    """A single strike with its call and/or put legs."""

    model_config = ConfigDict(frozen=True)

    strike: float
    expiry: date
    call: OptionQuote | None = None
    put: OptionQuote | None = None


class OptionChain(BaseModel):
    """A normalized option-chain snapshot for one underlying and (optionally) one expiry."""

    model_config = ConfigDict(frozen=True)

    underlying: str
    exchange: Exchange = Exchange.NSE
    spot: float = Field(description="Underlying spot/index level at snapshot time.")
    future_price: float = Field(description="Futures price used for Black-76 (never spot).")
    future_price_source: FuturePriceSource
    snapshot_ts: datetime = Field(description="Timezone-aware snapshot timestamp (Asia/Kolkata).")
    risk_free_rate: float = Field(description="Risk-free rate as a decimal (0.065 = 6.5%).")
    rows: list[ChainRow]

    @property
    def strikes(self) -> list[float]:
        return [r.strike for r in self.rows]


class GreeksResult(BaseModel):
    """Computed Black-76 Greeks for a single option leg, in presentation units.

    Carries the inputs that determined the result (`iv_used`, `t_years`, model, engine version) so
    every Greek is reproducible from storage.
    """

    model_config = ConfigDict(frozen=True)

    strike: float
    option_type: OptionType
    expiry: date
    iv_used: float = Field(description="IV (decimal) fed into the engine for this leg.")
    t_years: float = Field(description="Time to expiry in years (ACT/365).")
    price_model: str = "black76"
    engine_version: str

    price: float = Field(description="Theoretical option price at iv_used.")
    delta: float
    gamma: float
    theta_per_day: float
    vega_per_pct: float
    rho: float
