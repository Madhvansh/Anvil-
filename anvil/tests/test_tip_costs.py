"""Cost-illusion guard: a tip's edge must be COST-ADJUSTED. A trade that's positive on gross EV but
negative after the modeled India F&O round-trip is NOT a positive-edge tip."""

from anvil.strategy.types import BEARISH, NEUTRAL, Leg, TradeCandidate
from anvil.tips.build import round_trip_cost, tip_from_candidate


def _candidate(expected_value: float) -> TradeCandidate:
    return TradeCandidate(
        strategy="short_strangle",
        underlying="NIFTY",
        direction=NEUTRAL,
        legs=[
            Leg(side="SELL", lots=1, expiry="2026-06-24", ref_price=100.0, instrument_type="CE", strike=24200.0),
            Leg(side="SELL", lots=1, expiry="2026-06-24", ref_price=90.0, instrument_type="PE", strike=23800.0),
        ],
        lot_size=75,
        edge_prob=0.7,
        conviction=0.72,
        entry_debit_credit=-14250.0,
        max_loss=20000.0,
        max_profit=14250.0,
        breakevens=[23600.0, 24400.0],
        expected_value=expected_value,
        horizon_days=3.0,
        exit_rules={"target": 14000.0, "stop": 23600.0},
    )


def test_round_trip_cost_is_positive():
    assert round_trip_cost(_candidate(1000.0)) > 0


def test_cost_adjusted_ev_subtracts_costs():
    cand = _candidate(1000.0)
    tip = tip_from_candidate(cand, source="tip_backtest")
    assert tip.gross_ev == 1000.0
    assert tip.round_trip_cost > 0
    assert abs(tip.cost_adjusted_ev - (tip.gross_ev - tip.round_trip_cost)) < 0.01
    assert tip.cost_adjusted_ev < tip.gross_ev


def test_gross_positive_but_net_negative_is_flagged():
    # A thin edge that the cost stack eats: gross EV below the round-trip cost.
    cand = _candidate(10.0)
    tip = tip_from_candidate(cand, source="tip_backtest")
    assert tip.gross_ev > 0
    assert tip.cost_adjusted_ev < 0  # NOT a positive-edge tip after costs


def test_levels_and_fields_project_from_candidate():
    tip = tip_from_candidate(_candidate(1000.0), signals_fired=["iv_rank_term"], source="tip_live")
    assert tip.structure == "short_strangle"
    assert tip.target == 14000.0 and tip.stop == 23600.0
    assert tip.signals_fired == ["iv_rank_term"]
    assert len(tip.legs) == 2


def test_bearish_constant_imported_ok():
    assert BEARISH == "bearish"  # guards the strategy types import surface used above
