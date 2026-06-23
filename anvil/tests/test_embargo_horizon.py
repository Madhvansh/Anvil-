"""Phase 3 — the OOF embargo is the LABEL HORIZON, threaded into all three cert engines.

The walk-forward / combinatorial OOF edge checks purge an ``embargo`` so a multi-day label can't leak
train↔test. EQUITY already threaded its holding horizon; OPTIONS and LIVE were silently defaulting to
``embargo=5`` regardless of expiry. These tests prove the embargo now equals the observed issue→resolution
span (in independent trading days), not the old constant.
"""

from __future__ import annotations

import json
from datetime import date

from anvil.backtest.horizon import (
    build_day_index,
    embargo_from_pairs,
    robust_embargo,
    span_in_index,
)
from anvil.ingest.demo import build_demo_chain
from anvil.ledger.ledger import CalibrationLedger
from anvil.tips.store import IssuedTipStore, TipValidationStore


def test_horizon_helpers():
    idx = build_day_index(["2026-06-05", "2026-06-01", "2026-06-03", "2026-06-02", "2026-06-04"])
    assert span_in_index("2026-06-01", "2026-06-05", idx) == 4
    assert span_in_index("2026-06-02", "2026-06-04", idx) == 2
    assert span_in_index("2026-06-01", "1999-01-01", idx) == 0  # unknown endpoint → 0
    assert robust_embargo([3, 5, 2, 5]) == 5      # the MAX span (leak-safe)
    assert robust_embargo([]) == 5                # default when nothing measurable
    # NSE trading-day span 2026-06-01 → 2026-06-11 (no June holidays in the seed) = 8.
    assert embargo_from_pairs([("2026-06-01T09:15", "2026-06-11T16:00")]) == 8


class _LongHorizonArchive:
    """One demo chain issued on day 0 with an expiry 8 trading days out, over a contiguous run of days
    (so the day index spans the full label horizon)."""

    def __init__(self, days, settle: float):
        self._days = days
        self.issue, self.expiry, self.settle = days[0], days[-1], settle
        self._exp = self.expiry.isoformat()
        self._ts = f"{self.issue.isoformat()}T15:30:00+05:30"

    def trading_days(self, start=None, end=None):
        return list(self._days)

    def chains_on(self, d):
        if d == self.issue:
            return [build_demo_chain("NIFTY", spot=24000.0, expiry=self._exp, timestamp=self._ts)]
        return []

    def index_close_on(self, d, u):
        return self.settle if (d == self.expiry and u.upper() == "NIFTY") else None


def test_options_threads_label_horizon_not_default(tmp_path, monkeypatch):
    import anvil.backtest.tip_backtest as tb

    days = [date(2026, 6, d) for d in (1, 2, 3, 4, 5, 8, 9, 10, 11)]  # span(0→8) = 8 trading days
    arch = _LongHorizonArchive(days, settle=24010.0)
    captured: dict = {}
    real = tb.validate_cells

    def spy(*a, **k):
        captured["embargo"] = k.get("embargo")
        return real(*a, **k)

    monkeypatch.setattr(tb, "validate_cells", spy)
    led = CalibrationLedger(path=str(tmp_path / "l.duckdb"))
    store = TipValidationStore(path=str(tmp_path / "tv.duckdb"))
    try:
        res = tb.run_tip_backtest(arch, ["NIFTY"], led, store, min_samples=1)
        assert res["resolved"] >= 1, "the demo chain should issue + resolve a tip"
        assert captured["embargo"] == 8, "embargo must be the 8-day label horizon, not the default 5"
    finally:
        led.close()
        store.close()


def _insert_resolved_tip(istore, tip_id, created, resolve, ret, source="tip_live"):
    istore.con.execute(
        "INSERT INTO tips_issued (tip_id, ledger_forecast_id, underlying, created_ts, resolve_ts, "
        "structure, regime_bucket, tier, source, lot_size, round_trip_cost, max_loss, legs, payload, "
        "resolved, outcome, resolved_ts, net_pnl, ret) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [tip_id, "f1", "NIFTY", created, resolve, "short_strangle", "pin", "HEADLINE", source,
         50, 10.0, 100.0, json.dumps([]), json.dumps({"conviction": 0.6}), True, int(ret > 0),
         resolve, ret * 100.0, ret],
    )


def test_live_revalidate_threads_label_horizon(tmp_path, monkeypatch):
    import anvil.backtest.revalidate as rv

    istore = IssuedTipStore(path=str(tmp_path / "s.duckdb"))
    vstore = TipValidationStore(path=str(tmp_path / "v.duckdb"))
    created, resolve = "2026-06-01T15:30:00+05:30", "2026-06-11T16:00:00+05:30"  # 8 trading days
    for i in range(6):
        _insert_resolved_tip(istore, f"t{i}", created, resolve, 0.1 if i % 2 else -0.05)
    captured: dict = {}
    real = rv.validate_cells

    def spy(*a, **k):
        captured["embargo"] = k.get("embargo")
        return real(*a, **k)

    monkeypatch.setattr(rv, "validate_cells", spy)
    try:
        rv.revalidate_from_live(issued_store=istore, validation_store=vstore, sources=("tip_live",),
                                min_samples=1)
        assert captured["embargo"] == 8, "live embargo must be the 8-day label horizon, not the default 5"
    finally:
        istore.close()
        vstore.close()
