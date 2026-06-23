"""Structural forecast calibration + firewall + day-blocked significance (C3).

Touch forecasts resolve from the realized daily HIGH/LOW (true touch); VRP-rich resolves from realized
vol; the struct_* classes never leak into the public or tip curves; and the edge gate runs on
DAY-LEVEL blocks so a burst of correlated same-day touches cannot certify edge on count alone."""

from __future__ import annotations

from anvil.backtest.aggregate import cell_from_daily, validate_cells
from anvil.ledger.ledger import (
    KIND_PROB_TOUCH,
    KIND_VRP_RICH,
    PUBLIC_CLASSES,
    TIP_PUBLIC_CLASSES,
    CalibrationLedger,
    Forecast,
    source_class,
)


def _f(kind, params, prob):
    return Forecast("NIFTY", "2026-06-20T15:30:00+05:30", "2026-06-27", kind, params, prob,
                    24000.0, 24000.0, source="struct_live")


def test_touch_resolves_from_extreme_and_is_firewalled(tmp_path):
    led = CalibrationLedger(str(tmp_path / "l.duckdb"))
    try:
        up = _f(KIND_PROB_TOUCH, {"strike": 24500.0, "days": 5, "dir": "up"}, 0.6)
        led.record(up)
        assert led.resolve(up.id, 24600.0) == 1    # realized HIGH crossed the upper barrier
        dn = _f(KIND_PROB_TOUCH, {"strike": 23500.0, "days": 5, "dir": "down"}, 0.4)
        led.record(dn)
        assert led.resolve(dn.id, 23400.0) == 1     # realized LOW crossed the lower barrier
        miss = _f(KIND_PROB_TOUCH, {"strike": 25000.0, "days": 5, "dir": "up"}, 0.2)
        led.record(miss)
        assert led.resolve(miss.id, 24600.0) == 0   # high fell short → no touch
        vr = _f(KIND_VRP_RICH, {"implied_vol": 0.20, "days": 5}, 0.65)
        led.record(vr)
        assert led.resolve(vr.id, 0.15) == 1        # realized vol below implied → premium was rich

        # Firewall: struct_* forecasts never appear in the public or tip curves.
        assert led.metrics(classes=PUBLIC_CLASSES)["resolved_count"] == 0
        assert led.metrics_for_tips()["tip_live"]["resolved_count"] == 0
        assert led.metrics_for_structural()["struct_live"]["resolved_count"] == 4
        assert source_class("struct_live") == "struct_live"
        assert "struct_live" not in PUBLIC_CLASSES and "struct_live" not in TIP_PUBLIC_CLASSES
    finally:
        led.close()


def test_day_blocked_significance_does_not_inflate_on_correlated_touches():
    # 200 winning touches but only across 3 trading days. Per-label, n=200 would clear min_samples=50;
    # day-blocked (C3), n = 3 independent days → cannot clear the gate on count.
    days = ["2026-06-21", "2026-06-22", "2026-06-23"]
    cell = cell_from_daily([(d, 0.3) for d in days], conviction=0.5)
    reports, _pbo = validate_cells({("touch", "env", "NIFTY"): cell}, days, min_samples=50)
    rep = reports[0]
    assert rep.n == 3 and not rep.headline_eligible   # effective-n tracks days, not strike-labels
