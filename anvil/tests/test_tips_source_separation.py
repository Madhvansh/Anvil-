"""Hard rail (tips edition): issued-tip win/loss reliability lives on its OWN curve and must NEVER
blend into the market-implied probability calibration (PUBLIC_CLASSES) or the owner-only paper/today
curves — and vice versa. Mirrors test_source_separation.py for the new tip_* classes.
"""

from anvil.ledger.ledger import (
    KIND_PROB_ABOVE,
    PUBLIC_CLASSES,
    TIP_PUBLIC_CLASSES,
    CalibrationLedger,
    Forecast,
    source_class,
)
from anvil.tips.calibration import record_tip, resolve_tip, tip_calibration
from anvil.tips.types import Tip


def _tip(seq, source, conviction=0.6):
    return Tip(
        underlying="NIFTY",
        created_ts=f"2026-06-19T06:00:0{seq % 10}+00:00",
        resolve_ts="2026-06-24",
        horizon_days=3.0,
        structure="iron_condor",
        direction="neutral",
        legs=[{"side": "SELL", "lots": 1, "strike": 24000 + seq, "instrument_type": "CE"}],
        conviction=conviction,
        edge_prob=conviction,
        gross_ev=100.0,
        round_trip_cost=10.0,
        cost_adjusted_ev=90.0,
        max_loss=1000.0,
        max_profit=500.0,
        entry_debit_credit=-500.0,
        source=source,
    )


def _public_forecast(led, seq):
    f = Forecast(
        underlying="NIFTY", created_ts=f"2026-06-18T06:00:0{seq % 10}+00:00", resolve_ts="2026-06-25",
        kind=KIND_PROB_ABOVE, params={"level": 100.0, "seq": seq}, prob=0.9, spot=100.0,
        forward=100.0, source="backtest",
    )
    led.record(f)
    led.resolve(f.id, realized_value=101.0)


def test_source_class_maps_tip_classes():
    assert source_class("tip_backtest") == "tip_backtest"
    assert source_class("tip_live") == "tip_live"
    # the tip classes are not in the probability-calibration public set
    assert "tip_backtest" not in PUBLIC_CLASSES and "tip_live" not in PUBLIC_CLASSES
    assert set(TIP_PUBLIC_CLASSES) == {"tip_backtest", "tip_live"}


def test_tips_never_enter_the_public_probability_curve(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    # record + resolve several live tips (a couple winners, a couple losers)
    for i in range(6):
        t = _tip(i, source="tip_live")
        record_tip(led, t, spot=24000.0, forward=24010.0)
        resolve_tip(led, t, outcome=(i % 2 == 0))
    _public_forecast(led, 999)  # one genuinely public (backtest) probability forecast

    public = led.metrics()  # default = PUBLIC_CLASSES (backtest + live)
    assert public["resolved_count"] == 1                  # only the backtest row is public
    assert public["counts_by_class"].get("tip_live") == 6  # tips exist in the DB…
    # …but never on the public probability curve
    led.close()


def test_tip_curve_isolates_tip_classes(tmp_path):
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    for i in range(4):
        t = _tip(i, source="tip_live")
        record_tip(led, t, spot=24000.0, forward=24010.0)
        resolve_tip(led, t, outcome=True)
    for i in range(3):
        t = _tip(100 + i, source="tip_backtest")
        record_tip(led, t, spot=24000.0, forward=24010.0)
        resolve_tip(led, t, outcome=False)
    _public_forecast(led, 777)  # a public probability forecast must NOT leak into the tip curve

    tip_curves = tip_calibration(led)
    assert set(tip_curves) == {"tip_backtest", "tip_live"}
    assert tip_curves["tip_live"]["resolved_count"] == 4
    assert tip_curves["tip_backtest"]["resolved_count"] == 3
    led.close()
