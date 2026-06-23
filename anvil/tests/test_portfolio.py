"""Beta-weighted portfolio Greeks."""

import pytest

from anvil.engine.portfolio import beta_weighted_greeks
from anvil.models import OptionType, Position


def test_beta_weighted_delta_equity():
    pos = [
        Position(symbol="RELIANCE", underlying="RELIANCE", instrument_type="EQ",
                 quantity=100, underlying_price=2950.0, ltp=2950.0, beta=1.2)
    ]
    pr = beta_weighted_greeks(pos, benchmark="NIFTY", benchmark_price=24000.0)
    assert pr.net_delta == pytest.approx(100.0)
    # BWD = 100 * 1.2 * (2950/24000)
    assert pr.beta_weighted_delta == pytest.approx(100 * 1.2 * (2950 / 24000), abs=1e-6)


def test_short_straddle_delta_near_zero():
    exp = "2026-07-31"
    pos = [
        Position(symbol="NIFTYCE", underlying="NIFTY", instrument_type="CE",
                 option_type=OptionType.CALL, strike=24000.0, expiry=exp,
                 quantity=-75, underlying_price=24000.0, ltp=120.0, iv=0.13),
        Position(symbol="NIFTYPE", underlying="NIFTY", instrument_type="PE",
                 option_type=OptionType.PUT, strike=24000.0, expiry=exp,
                 quantity=-75, underlying_price=24000.0, ltp=125.0, iv=0.135),
    ]
    pr = beta_weighted_greeks(pos, benchmark="NIFTY", benchmark_price=24000.0,
                              now="2026-06-17T06:00:00+00:00")
    # near-ATM straddle: net delta small relative to one lot
    assert abs(pr.net_delta) < 30
    # short options => negative gamma, positive theta (collect decay)
    assert pr.net_gamma < 0
    assert pr.net_theta > 0


def test_missing_benchmark_price_notes():
    pos = [Position(symbol="X", underlying="X", instrument_type="EQ", quantity=10,
                    underlying_price=100.0, ltp=100.0, beta=1.0)]
    pr = beta_weighted_greeks(pos, benchmark="NIFTY", benchmark_price=0.0)
    assert pr.beta_weighted_delta == 0.0
    assert pr.notes
