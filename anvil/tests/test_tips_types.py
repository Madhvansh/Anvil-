"""The Tip id must be deterministic (idempotent re-issue) and the payload JSON-safe."""

from anvil.tips.types import HEADLINE, TIP_DISCLAIMER, Tip


def _tip(**over):
    base = dict(
        underlying="NIFTY",
        created_ts="2026-06-19T06:00:00+00:00",
        resolve_ts="2026-06-24",
        horizon_days=3.0,
        structure="iron_condor",
        direction="neutral",
        legs=[{"side": "SELL", "lots": 1, "strike": 24000, "instrument_type": "CE"}],
        conviction=0.65,
        edge_prob=0.62,
        gross_ev=1200.0,
        round_trip_cost=180.0,
        cost_adjusted_ev=1020.0,
        max_loss=5000.0,
        max_profit=2500.0,
        entry_debit_credit=-2500.0,
    )
    base.update(over)
    return Tip(**base)


def test_tip_id_is_deterministic():
    assert _tip().tip_id == _tip().tip_id


def test_tip_id_changes_with_legs():
    a = _tip()
    b = _tip(legs=[{"side": "SELL", "lots": 2, "strike": 24000, "instrument_type": "CE"}])
    assert a.tip_id != b.tip_id


def test_to_dict_is_json_safe_and_carries_disclaimer():
    d = _tip(tier=HEADLINE, max_profit=float("nan")).to_dict()
    assert d["tip_id"]
    assert d["tier"] == HEADLINE
    assert d["disclaimer"] == TIP_DISCLAIMER
    assert d["max_profit"] is None  # NaN sanitized by json_safe
