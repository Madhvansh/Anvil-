"""Scenario grid — "if the index moves X% and IV shifts Y, what happens to my book?"

Reprices every position with Black-76 (``engine.greeks.price``) across a grid of spot shocks
(applied per-position via beta) and absolute IV shifts. Model value is used on both sides so a
cell's P&L is the pure Greek-driven change, not market/model basis. The intuitive
risk-first view the brief asks for, not a wall of raw Greeks.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..models import OptionChain, Position
from . import greeks as gk
from .util import year_fraction

DEFAULT_SPOT_SHOCKS = [-0.03, -0.02, -0.01, 0.0, 0.01, 0.02, 0.03]
DEFAULT_VOL_SHIFTS = [-0.05, 0.0, 0.05]  # absolute IV shifts (vol points)


def _underlying_level(pos: Position, chain: OptionChain) -> float:
    if pos.underlying_price and pos.underlying_price > 0:
        return float(pos.underlying_price)
    if pos.underlying == chain.underlying:
        return float(chain.spot)
    if pos.ltp and pos.instrument_type in ("EQ", "FUT"):
        return float(pos.ltp)
    return float(chain.spot)


def _foreign_unknown(pos: Position, chain: OptionChain) -> bool:
    """An option on a different underlying than the chain whose spot we don't know — we can't
    reprice it against this index, so callers hold it flat rather than mispricing it at index spot."""
    return pos.underlying != chain.underlying and not (pos.underlying_price and pos.underlying_price > 0)


def _position_value(pos: Position, chain: OptionChain, spot_shock: float, vol_shift: float, days_fwd: float, r: float) -> float:
    if pos.instrument_type in ("EQ", "FUT"):
        return _underlying_level(pos, chain) * (1.0 + pos.beta * spot_shock) * pos.quantity
    if pos.option_type is None or pos.strike is None:
        return 0.0
    if _foreign_unknown(pos, chain):
        return float(pos.ltp or 0.0) * pos.quantity  # hold flat at current mark
    level = _underlying_level(pos, chain) * (1.0 + pos.beta * spot_shock)
    T = max(year_fraction(pos.expiry or chain.expiry, chain.timestamp) - days_fwd / 365.0, 1e-6)
    sigma = max((pos.iv or 0.15) + vol_shift, 1e-3)
    return float(gk.price(pos.option_type, level, pos.strike, T, r, sigma)) * pos.quantity


def _book_value(positions: list[Position], chain: OptionChain, spot_shock: float, vol_shift: float, days_fwd: float, r: float) -> float:
    return float(sum(_position_value(p, chain, spot_shock, vol_shift, days_fwd, r) for p in positions))


def scenario_grid(
    chain: OptionChain,
    positions: list[Position] | None,
    spot_shocks: list[float] | None = None,
    vol_shifts: list[float] | None = None,
    horizon_days: float = 0.0,
    r: float | None = None,
) -> dict:
    r = SETTINGS.risk_free_rate if r is None else r
    spot_shocks = spot_shocks or DEFAULT_SPOT_SHOCKS
    vol_shifts = vol_shifts or DEFAULT_VOL_SHIFTS
    positions = positions or []
    base = _book_value(positions, chain, 0.0, 0.0, 0.0, r)

    cells: list[dict] = []
    for vs in vol_shifts:
        for ss in spot_shocks:
            val = _book_value(positions, chain, ss, vs, horizon_days, r)
            cells.append({"spot_shock": ss, "vol_shift": vs, "pnl": round(val - base, 2)})

    return {
        "underlying": chain.underlying,
        "spot": chain.spot,
        "base_value": round(base, 2),
        "spot_shocks": spot_shocks,
        "vol_shifts": vol_shifts,
        "horizon_days": horizon_days,
        "cells": cells,
        "worst": min(cells, key=lambda c: c["pnl"]) if (positions and cells) else None,
        "best": max(cells, key=lambda c: c["pnl"]) if (positions and cells) else None,
        "has_positions": bool(positions),
    }
