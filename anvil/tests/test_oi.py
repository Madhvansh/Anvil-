"""OI analytics: buildup classification, PCR, max pain, walls."""

from anvil.engine import oi as oi_mod
from anvil.models import ChainRow, OptionChain, OptionType


def test_classify_buildup():
    assert oi_mod.classify_buildup(+1, +1) == "long_buildup"
    assert oi_mod.classify_buildup(-1, +1) == "short_buildup"
    assert oi_mod.classify_buildup(+1, -1) == "short_covering"
    assert oi_mod.classify_buildup(-1, -1) == "long_unwinding"


def _chain():
    rows = [
        ChainRow(strike=100, option_type=OptionType.CALL, oi=100, volume=50, ltp=5),
        ChainRow(strike=110, option_type=OptionType.CALL, oi=300, volume=80, ltp=2),
        ChainRow(strike=100, option_type=OptionType.PUT, oi=400, volume=120, ltp=4),
        ChainRow(strike=90, option_type=OptionType.PUT, oi=250, volume=60, ltp=1),
    ]
    return OptionChain(underlying="X", spot=100, expiry="2026-12-31", timestamp="2026-06-17T06:00:00+00:00", rows=rows)


def test_pcr():
    ch = _chain()
    # put OI 650 / call OI 400
    assert oi_mod.pcr_oi(ch) == 650 / 400


def test_oi_walls():
    walls = oi_mod.oi_walls(_chain(), n=1)
    assert walls.call_resistance[0][0] == 110  # highest call OI strike
    assert walls.put_support[0][0] == 100  # highest put OI strike


def test_max_pain_is_a_listed_strike():
    ch = _chain()
    mp = oi_mod.max_pain(ch)
    assert mp in ch.strikes()
