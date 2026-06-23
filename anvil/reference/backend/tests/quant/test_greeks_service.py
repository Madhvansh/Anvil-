"""greeks_service: presentation-unit scaling + chain-level computation."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from oip.domain.enums import Exchange, FuturePriceSource, OptionType
from oip.domain.models import ChainRow, OptionChain, OptionQuote
from oip.quant import black76, greeks_service

pytestmark = [pytest.mark.unit]

IST = ZoneInfo("Asia/Kolkata")


def test_leg_scaling_matches_raw_engine():
    F, K, t, r, iv = 22000.0, 22000.0, 30 / 365, 0.065, 0.14
    res = greeks_service.compute_leg_greeks(
        option_type="c", future_price=F, strike=K, t_years=t,
        risk_free_rate=r, iv=iv, expiry=date(2026, 7, 17),
    )
    assert res.delta == pytest.approx(black76.delta("c", F, K, t, r, iv))
    assert res.gamma == pytest.approx(black76.gamma(F, K, t, r, iv))
    assert res.theta_per_day == pytest.approx(black76.theta("c", F, K, t, r, iv) / 365.0)
    assert res.vega_per_pct == pytest.approx(black76.vega(F, K, t, r, iv) / 100.0)
    assert res.rho == pytest.approx(black76.rho("c", F, K, t, r, iv) / 100.0)
    assert res.price == pytest.approx(black76.price("c", F, K, t, r, iv))
    assert res.engine_version == black76.ENGINE_VERSION
    assert res.price_model == "black76"
    assert res.iv_used == pytest.approx(iv)
    assert res.t_years == pytest.approx(t)


def test_year_fraction_act365():
    snap = datetime(2026, 6, 12, 15, 30, tzinfo=IST)
    expiry = date(2026, 6, 26)  # 14 calendar days to 15:30 IST
    assert greeks_service.year_fraction(snap, expiry) == pytest.approx(14 / 365, rel=1e-9)


def _sample_chain() -> OptionChain:
    snap = datetime(2026, 6, 12, 15, 30, tzinfo=IST)
    rows = [
        ChainRow(
            strike=22000.0, expiry=date(2026, 6, 26),
            call=OptionQuote(option_type=OptionType.CALL, last_price=200.0, iv_source=0.14),
            put=OptionQuote(option_type=OptionType.PUT, last_price=190.0, iv_source=0.15),
        ),
        ChainRow(
            strike=22500.0, expiry=date(2026, 6, 26),
            call=OptionQuote(option_type=OptionType.CALL, last_price=60.0, iv_source=0.16),
            put=OptionQuote(option_type=OptionType.PUT, last_price=420.0, iv_source=0.17),
        ),
    ]
    return OptionChain(
        underlying="NIFTY", exchange=Exchange.NSE, spot=21990.0, future_price=22010.0,
        future_price_source=FuturePriceSource.DERIVED_COST_OF_CARRY, snapshot_ts=snap,
        risk_free_rate=0.065, rows=rows,
    )


def test_compute_chain_greeks_one_per_leg():
    chain = _sample_chain()
    results = greeks_service.compute_chain_greeks(chain)
    assert len(results) == 4  # 2 strikes x (call + put)
    for res in results:
        assert res.engine_version == black76.ENGINE_VERSION
        assert res.t_years > 0
    # spot-check one leg vs the engine directly
    leg = next(r for r in results if r.strike == 22000.0 and r.option_type == OptionType.CALL)
    t = greeks_service.year_fraction(chain.snapshot_ts, date(2026, 6, 26))
    assert leg.delta == pytest.approx(black76.delta("c", 22010.0, 22000.0, t, 0.065, 0.14))
