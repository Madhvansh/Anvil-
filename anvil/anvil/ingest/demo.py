"""Offline synthetic data — lets the whole pipeline and tests run with zero API keys.

The synthetic chain is *self-consistent*: prices are generated from a parametric IV
smile via Black-Scholes, so computed IV round-trips and Greeks are well-defined. OI is
shaped realistically (calls heavier above spot, puts below, round-strike bumps) so GEX,
max pain, and the zero-gamma flip behave like the real thing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np

from ..config import lot_size, strike_step
from ..models import ChainRow, OptionChain, OptionType, Position
from .base import Connector


def _next_weekly_expiry(now: datetime) -> datetime:
    # NSE weekly index expiry currently Thursday (Tue for some) — use Thursday as default.
    days_ahead = (3 - now.weekday()) % 7  # Thursday == 3
    if days_ahead == 0:
        days_ahead = 7
    exp = now + timedelta(days=days_ahead)
    return exp.replace(hour=10, minute=0, second=0, microsecond=0)  # 15:30 IST


def build_demo_chain(
    underlying: str = "NIFTY",
    spot: float = 24000.0,
    expiry: str | None = None,
    timestamp: str | None = None,
    n_strikes: int = 40,
    atm_iv: float = 0.13,
    skew_slope: float = 0.6,
    curvature: float = 1.2,
    seed: int = 7,
) -> OptionChain:
    """Build a deterministic, self-consistent synthetic option chain."""
    from ..engine import greeks as gk
    from ..engine.util import year_fraction

    now = datetime.now(timezone.utc)
    ts = timestamp or now.isoformat()
    exp = expiry or _next_weekly_expiry(now).date().isoformat()
    T = max(year_fraction(exp, ts), 1e-6)
    # Black-76 prices off the forward; derive a cost-of-carry future for the fixture.
    forward = spot * float(np.exp((0.065 - 0.012) * T))

    step = strike_step(underlying)
    lot = lot_size(underlying)
    atm = round(spot / step) * step
    strikes = np.array([atm + i * step for i in range(-n_strikes, n_strikes + 1)], dtype=float)

    rows: list[ChainRow] = []
    rng = np.random.default_rng(seed)
    for k in strikes:
        m = np.log(k / spot)  # moneyness
        iv = float(max(atm_iv + skew_slope * (-m) + curvature * m * m, 0.04))
        for ot in (OptionType.CALL, OptionType.PUT):
            price = float(gk.price(ot, forward, k, T, 0.065, iv))
            price = max(price, 0.05)
            # OI shape: calls heavier above spot, puts below; round-strike bumps.
            if ot == OptionType.CALL:
                center = spot * 1.012
            else:
                center = spot * 0.988
            shape = np.exp(-((k - center) ** 2) / (2 * (6 * step) ** 2))
            bump = 1.6 if (k % (5 * step) == 0) else 1.0
            oi = float(round(shape * bump * 9_000_00 + rng.integers(0, 50_000)))  # ~ in units
            oi_change = float(round((shape - 0.5) * 200000 * np.sign(np.sin(k))))
            vol = float(round(oi * 0.35))
            rows.append(
                ChainRow(
                    strike=float(k),
                    option_type=ot,
                    ltp=round(price, 2),
                    bid=round(price * 0.995, 2),
                    ask=round(price * 1.005, 2),
                    oi=oi,
                    oi_change=oi_change,
                    volume=vol,
                    iv=iv,
                )
            )

    return OptionChain(
        underlying=underlying,
        spot=spot,
        expiry=exp,
        timestamp=ts,
        rows=rows,
        future_price=round(forward, 2),
        future_price_source="fixture_derived",
        vix=round(atm_iv * 100, 2),
        lot_size=lot,
        underlying_prev_close=round(spot * 0.997, 2),
    )


def demo_positions(spot: float = 24000.0, expiry: str | None = None) -> list[Position]:
    """A small mixed book: short NIFTY ATM straddle + a beta'd stock position."""
    now = datetime.now(timezone.utc)
    exp = expiry or _next_weekly_expiry(now).date().isoformat()
    atm = round(spot / strike_step("NIFTY")) * strike_step("NIFTY")
    lot = lot_size("NIFTY")
    return [
        Position(
            symbol=f"NIFTY{atm}CE", underlying="NIFTY", instrument_type="CE",
            strike=float(atm), option_type=OptionType.CALL, expiry=exp,
            quantity=-lot, lot_size=lot, avg_price=120.0, ltp=120.0,
            underlying_price=spot, iv=0.13, beta=1.0,
        ),
        Position(
            symbol=f"NIFTY{atm}PE", underlying="NIFTY", instrument_type="PE",
            strike=float(atm), option_type=OptionType.PUT, expiry=exp,
            quantity=-lot, lot_size=lot, avg_price=130.0, ltp=130.0,
            underlying_price=spot, iv=0.135, beta=1.0,
        ),
        Position(
            symbol="RELIANCE", underlying="RELIANCE", instrument_type="EQ",
            quantity=250, lot_size=1, avg_price=2800.0, ltp=2950.0,
            underlying_price=2950.0, beta=1.15,
        ),
    ]


class DemoConnector(Connector):
    name = "demo"
    provides_chain = True
    provides_positions = True

    def __init__(self, spot: float = 24000.0):
        self.spot = spot

    def get_chain(self, underlying: str = "NIFTY", expiry: str | None = None) -> OptionChain:
        spot = {"NIFTY": 24000.0, "BANKNIFTY": 52000.0, "FINNIFTY": 23500.0}.get(
            underlying.upper(), self.spot
        )
        return build_demo_chain(underlying.upper(), spot=spot, expiry=expiry)

    def get_expiries(self, underlying: str) -> list[str]:
        now = datetime.now(timezone.utc)
        return [(_next_weekly_expiry(now) + timedelta(days=7 * i)).date().isoformat() for i in range(4)]

    def get_historical_candles(
        self, underlying: str = "NIFTY", interval_min: int = 15, start: str | None = None, end: str | None = None
    ) -> list[tuple[str, float, float, float, float]]:
        """Deterministic synthetic intraday path (seeded) so 'today' replay runs with ZERO keys —
        market-closed and CI safe. ~25 candles over an IST 09:15->15:30 session."""
        base = {"NIFTY": 24000.0, "BANKNIFTY": 52000.0, "FINNIFTY": 23500.0, "SENSEX": 79000.0}.get(
            underlying.upper(), self.spot
        )
        ist = timezone(timedelta(hours=5, minutes=30))
        day = datetime.now(ist).date()
        open_dt = datetime(day.year, day.month, day.day, 9, 15, tzinfo=ist)
        n = max(1, int((375) / max(interval_min, 1)))  # 375 trading minutes / interval
        rng = np.random.default_rng(7)
        out: list[tuple[str, float, float, float, float]] = []
        spot = base
        for i in range(n):
            ts = (open_dt + timedelta(minutes=i * interval_min)).isoformat()
            o = spot
            spot = max(spot + float(rng.normal(0.0, base * 0.0015)), 1.0)
            c = spot
            out.append((ts, round(o, 2), round(max(o, c) * 1.001, 2), round(min(o, c) * 0.999, 2), round(c, 2)))
        return out

    def get_positions(self) -> list[Position]:
        return demo_positions(self.spot)
