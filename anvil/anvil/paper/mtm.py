"""Mark-to-market + net Greeks for paper positions.

Reuses ``engine.scenarios._book_value`` (Black-76 via ``engine.greeks.price``) and
``engine.portfolio.beta_weighted_greeks`` so paper marks come from the EXACT pricing path that
``scenario``/``montecarlo`` already trust — one pricing source of truth, no drift. Unrealized P&L
is measured against this model value; realized P&L (on close) uses actual gateway fills.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..engine.portfolio import beta_weighted_greeks
from ..engine.scenarios import _book_value
from ..models import OptionChain, Position
from .state import PaperPosition


def legs_to_positions(pos: PaperPosition, chain: OptionChain) -> list[Position]:
    """Project paper legs onto engine ``Position`` objects marked at the CURRENT chain."""
    out: list[Position] = []
    lot = pos.lot_size
    for leg in pos.legs:
        qty = leg.sign * leg.qty(lot)  # signed contract quantity
        iv = None
        ltp = leg.entry_price
        if leg.option_type is not None and leg.strike is not None:
            row = chain.row(leg.strike, leg.option_type)
            if row is not None:
                iv = row.iv
                if row.bid and row.ask and row.bid > 0 and row.ask > 0:
                    ltp = (row.bid + row.ask) / 2.0
                elif row.ltp:
                    ltp = row.ltp
            under_px = chain.spot
        else:  # FUT / EQ
            under_px = float(chain.future_price or chain.spot)
            ltp = under_px
        out.append(
            Position(
                symbol=leg.symbol or f"{pos.underlying}-{leg.instrument_type}",
                underlying=pos.underlying,
                instrument_type=leg.instrument_type,
                quantity=float(qty),
                lot_size=lot,
                avg_price=float(leg.entry_price),
                ltp=float(ltp),
                strike=leg.strike,
                option_type=leg.option_type,
                expiry=leg.expiry,
                underlying_price=float(under_px),
                iv=iv,
                beta=1.0,
            )
        )
    return out


def mark_value(pos: PaperPosition, chain: OptionChain) -> float:
    """Signed model value of the position now (what holding it is worth)."""
    r = SETTINGS.risk_free_rate
    positions = legs_to_positions(pos, chain)
    return float(_book_value(positions, chain, 0.0, 0.0, 0.0, r))


def net_greeks(pos: PaperPosition, chain: OptionChain) -> dict:
    positions = legs_to_positions(pos, chain)
    pr = beta_weighted_greeks(positions, benchmark=pos.underlying, benchmark_price=chain.spot)
    return {
        "net_delta": round(pr.net_delta, 2),
        "net_gamma": round(pr.net_gamma, 4),
        "net_theta": round(pr.net_theta, 2),
        "net_vega": round(pr.net_vega, 2),
    }
