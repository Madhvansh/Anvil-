"""Chain-level Greeks: turn raw Black-76 outputs into presentation-unit `GreeksResult`s.

This is the only place academic units are scaled for display (theta/365, vega/100, rho/100), so
the engine in black76.py stays a clean math oracle.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from ..constants import IST_TZ
from ..domain.enums import OptionType
from ..domain.models import GreeksResult, OptionChain
from . import black76

_IST = ZoneInfo(IST_TZ)
_MARKET_CLOSE = time(15, 30)
_SECONDS_PER_YEAR = 365.0 * 24 * 3600  # ACT/365


def year_fraction(snapshot_ts: datetime, expiry: date) -> float:
    """ACT/365 years from the snapshot to the expiry's 15:30 IST market close."""
    if snapshot_ts.tzinfo is None:
        snapshot_ts = snapshot_ts.replace(tzinfo=_IST)
    expiry_dt = datetime.combine(expiry, _MARKET_CLOSE, tzinfo=_IST)
    return (expiry_dt - snapshot_ts).total_seconds() / _SECONDS_PER_YEAR


def _as_enum(option_type: OptionType | str) -> OptionType:
    if isinstance(option_type, OptionType):
        return option_type
    return OptionType(black76._flag(option_type))


def compute_leg_greeks(
    *,
    option_type: OptionType | str,
    future_price: float,
    strike: float,
    t_years: float,
    risk_free_rate: float,
    iv: float,
    expiry: date,
) -> GreeksResult:
    g = black76.all_greeks(option_type, future_price, strike, t_years, risk_free_rate, iv)
    return GreeksResult(
        strike=strike,
        option_type=_as_enum(option_type),
        expiry=expiry,
        iv_used=iv,
        t_years=t_years,
        price_model="black76",
        engine_version=black76.ENGINE_VERSION,
        price=g.price,
        delta=g.delta,
        gamma=g.gamma,
        theta_per_day=g.theta / 365.0,
        vega_per_pct=g.vega / 100.0,
        rho=g.rho / 100.0,
    )


def compute_chain_greeks(chain: OptionChain) -> list[GreeksResult]:
    """Compute Greeks for every present leg with a usable IV. Legs without an IV (or a price to
    back one out) are skipped rather than guessed."""
    results: list[GreeksResult] = []
    for row in chain.rows:
        t = year_fraction(chain.snapshot_ts, row.expiry)
        if t <= 0:
            continue
        for leg in (row.call, row.put):
            if leg is None:
                continue
            iv = leg.iv_source
            if iv is None or iv <= 0:
                if leg.last_price and leg.last_price > 0:
                    try:
                        iv = black76.implied_vol(
                            leg.option_type, leg.last_price, chain.future_price,
                            row.strike, t, chain.risk_free_rate,
                        )
                    except ValueError:
                        continue
                else:
                    continue
            results.append(
                compute_leg_greeks(
                    option_type=leg.option_type,
                    future_price=chain.future_price,
                    strike=row.strike,
                    t_years=t,
                    risk_free_rate=chain.risk_free_rate,
                    iv=iv,
                    expiry=row.expiry,
                )
            )
    return results
