"""GEX: deterministic sign-convention checks + structural checks on a realistic chain."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from oip.analytics import gex
from oip.domain.enums import Exchange, FuturePriceSource, OptionType
from oip.domain.models import ChainRow, OptionChain, OptionQuote

pytestmark = [pytest.mark.unit]
_IST = ZoneInfo("Asia/Kolkata")


def _one_sided(option_type: OptionType) -> OptionChain:
    rows = []
    for k in range(21800, 22201, 100):
        q = OptionQuote(option_type=option_type, oi=1_000_000, volume=1000, iv_source=0.13)
        rows.append(
            ChainRow(
                strike=float(k), expiry=date(2026, 6, 26),
                call=q if option_type == OptionType.CALL else None,
                put=q if option_type == OptionType.PUT else None,
            )
        )
    return OptionChain(
        underlying="NIFTY", exchange=Exchange.NSE, spot=22000.0, future_price=22000.0,
        future_price_source=FuturePriceSource.NSE_FUTURES,
        snapshot_ts=datetime(2026, 6, 12, 15, 30, tzinfo=_IST), risk_free_rate=0.065, rows=rows,
    )


def test_calls_only_give_positive_gex():
    res = gex.compute_gex(_one_sided(OptionType.CALL))
    assert res.total_gex > 0
    assert all(v > 0 for v in res.per_strike.values())
    assert res.needs_nse_validation is True  # honesty flag must be set


def test_puts_only_give_negative_gex():
    res = gex.compute_gex(_one_sided(OptionType.PUT))
    assert res.total_gex < 0
    assert all(v < 0 for v in res.per_strike.values())


def test_dealer_sign_flips_total():
    pos = gex.compute_gex(_one_sided(OptionType.CALL), dealer_sign=1).total_gex
    neg = gex.compute_gex(_one_sided(OptionType.CALL), dealer_sign=-1).total_gex
    assert pos == pytest.approx(-neg)


def test_gex_structure_on_wide_chain(wide_chain):
    res = gex.compute_gex(wide_chain)
    assert res.per_strike  # non-empty
    assert isinstance(res.total_gex, float)
    assert all(v > 0 for _, v in res.call_walls)
    assert all(v < 0 for _, v in res.put_walls)
