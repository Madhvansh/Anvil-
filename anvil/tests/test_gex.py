"""GEX: dealer sign convention, spot-squared scaling, zero-gamma flip detection (Black-76)."""

import math

import pytest

from anvil.engine import greeks as gk
from anvil.engine.forward import resolve_forward
from anvil.engine.gex import compute_gex
from anvil.engine.util import year_fraction
from anvil.ingest.demo import build_demo_chain
from anvil.models import ChainRow, OptionChain, OptionType

TS = "2026-06-17T06:00:00+00:00"
EXP = "2026-07-31"


def _one(option_type, strike=24000, oi=100000, iv=0.13):
    return OptionChain(
        underlying="NIFTY", spot=24000, expiry=EXP, timestamp=TS, lot_size=75,
        rows=[ChainRow(strike=strike, option_type=option_type, oi=oi, iv=iv)],
    )


def test_sign_convention_call_positive_put_negative():
    assert compute_gex(_one(OptionType.CALL)).total_gex > 0
    assert compute_gex(_one(OptionType.PUT)).total_gex < 0


def test_spot_squared_scaling_formula():
    ch = _one(OptionType.CALL, iv=0.13)
    res = compute_gex(ch, r=0.065, q=0.012)
    T = year_fraction(EXP, TS)
    F, _ = resolve_forward(ch, 0.065, 0.012)
    g = float(gk.gamma(F, 24000, T, 0.065, 0.13))
    expected = g * 100000 * 75 * (24000**2) * 0.01  # scale uses spot
    assert res.total_gex == pytest.approx(expected, rel=1e-9)


def test_zero_gamma_flip_found_on_demo_chain():
    ch = build_demo_chain("NIFTY", spot=24000.0, expiry=EXP, timestamp=TS)
    res = compute_gex(ch)
    assert res.zero_gamma_flip is not None
    assert abs(res.zero_gamma_flip - ch.spot) / ch.spot < 0.12
    assert math.isfinite(res.total_gex)
    assert res.forward_source  # provenance is tagged
