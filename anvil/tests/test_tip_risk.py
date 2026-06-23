"""Phase 4 per-ticket risk distribution (tips/risk.py): leg->position projection, modeled return
samples, and the repeated-bet risk-of-ruin / forward-drawdown Monte-Carlo."""

from anvil.models import OptionType
from anvil.tips.risk import legs_to_positions, modeled_returns, ruin_and_drawdown


def _legs():
    return [
        {"side": "SELL", "lots": 2, "strike": 24000.0, "option_type": "CE", "instrument_type": "CE",
         "ref_price": 120.0, "expiry": "2026-07-31", "symbol": "C24000"},
        {"side": "BUY", "lots": 2, "strike": 24500.0, "option_type": "CE", "instrument_type": "CE",
         "ref_price": 40.0, "expiry": "2026-07-31", "symbol": "C24500"},
    ]


def test_legs_to_positions_signs_and_fields():
    pos = legs_to_positions(_legs(), lot_size=75, underlying="NIFTY", chain=None)
    assert len(pos) == 2
    assert pos[0].quantity == -2 * 75  # SELL -> negative, * lot size
    assert pos[1].quantity == 2 * 75   # BUY -> positive
    assert pos[0].option_type == OptionType.CALL
    assert pos[0].ltp == 120.0 and pos[0].strike == 24000.0
    assert pos[0].iv is None  # no chain supplied


def test_modeled_returns_counts():
    r = modeled_returns(0.6, 0.1, -0.2, n=100)
    assert len(r) == 100
    assert r.count(0.1) == 60 and r.count(-0.2) == 40


def test_ruin_deterministic_and_directional():
    pos = modeled_returns(0.7, 0.05, -0.05, n=200)   # +EV book
    neg = modeled_returns(0.3, 0.05, -0.05, n=200)   # -EV book
    a, a2 = ruin_and_drawdown(pos, seed=1), ruin_and_drawdown(pos, seed=1)
    assert a == a2  # deterministic under seed
    b = ruin_and_drawdown(neg, seed=1)
    assert a["risk_of_ruin"] < b["risk_of_ruin"]  # a worse edge ruins more often
    assert a["forward_drawdown"]["p95"] >= a["forward_drawdown"]["p50"] >= 0.0
    assert a["basis"] == "modeled"


def test_ruin_none_on_empty():
    assert ruin_and_drawdown([]) is None
