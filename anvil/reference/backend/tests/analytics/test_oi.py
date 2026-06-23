"""OI analytics: PCR, max pain (deterministic constructions), walls, buildup."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from oip.analytics import oi
from oip.domain.enums import Exchange, FuturePriceSource, OptionType
from oip.domain.models import ChainRow, OptionChain, OptionQuote

pytestmark = [pytest.mark.unit]
_IST = ZoneInfo("Asia/Kolkata")


def _chain(spec, future=22000.0):
    # spec: list of (strike, call_oi, put_oi); each leg gets call vol 100, put vol 200
    rows = [
        ChainRow(
            strike=float(k), expiry=date(2026, 6, 26),
            call=OptionQuote(option_type=OptionType.CALL, oi=c, volume=100),
            put=OptionQuote(option_type=OptionType.PUT, oi=p, volume=200),
        )
        for k, c, p in spec
    ]
    return OptionChain(
        underlying="NIFTY", exchange=Exchange.NSE, spot=future, future_price=future,
        future_price_source=FuturePriceSource.NSE_FUTURES,
        snapshot_ts=datetime(2026, 6, 12, 15, 30, tzinfo=_IST), risk_free_rate=0.065, rows=rows,
    )


def test_pcr_oi_and_volume():
    ch = _chain([(21900, 100, 300), (22000, 200, 200), (22100, 300, 100)])
    assert oi.pcr_oi(ch) == pytest.approx(600 / 600)   # 1.0
    assert oi.pcr_volume(ch) == pytest.approx(600 / 300)  # puts 3*200 / calls 3*100 = 2.0


def test_max_pain_all_oi_at_one_strike():
    ch = _chain([(21900, 0, 0), (22000, 1000, 1000), (22100, 0, 0)])
    assert oi.max_pain(ch) == 22000.0


def test_max_pain_symmetric_uniform_is_center():
    ch = _chain([(21800, 1000, 1000), (21900, 1000, 1000), (22000, 1000, 1000),
                 (22100, 1000, 1000), (22200, 1000, 1000)])
    assert oi.max_pain(ch) == 22000.0


def test_oi_walls(wide_chain):
    walls = oi.oi_walls(wide_chain, n=2)
    assert len(walls.call_resistance) == 2 and len(walls.put_support) == 2
    assert walls.call_resistance[0][0] == 22200.0  # call OI peak (by construction)
    assert walls.put_support[0][0] == 21800.0       # put OI peak


def test_classify_buildup():
    assert oi.classify_buildup(1, 1) == "long_buildup"
    assert oi.classify_buildup(-1, 1) == "short_buildup"
    assert oi.classify_buildup(1, -1) == "short_covering"
    assert oi.classify_buildup(-1, -1) == "long_unwinding"
