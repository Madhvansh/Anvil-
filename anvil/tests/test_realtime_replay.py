"""Phase 3 — realtime/replay loop. Determinism is the reproducibility requirement; market-hours
gating and the equity-point cadence are the loop contracts. Deterministic on the demo path."""

from __future__ import annotations

from datetime import datetime

from anvil.live.clock import IST, LiveClock, ReplayClock, is_market_open
from anvil.live.realtime import RealtimeEngine

START = "2026-06-19T03:45:00+00:00"
EXPIRY = "2026-06-26"


def _replay(seed=5, steps=6):
    return RealtimeEngine().replay(["NIFTY"], start_ts=START, expiry=EXPIRY, steps=steps, cadence_s=14400, seed=seed)


def test_replay_is_deterministic():
    r1, r2 = _replay(), _replay()
    assert [p["equity"] for p in r1["equity_curve"]] == [p["equity"] for p in r2["equity_curve"]]
    assert r1["summary"]["net_pnl"] == r2["summary"]["net_pnl"]
    assert r1["trades"]["n_total"] == r2["trades"]["n_total"]


def test_replay_records_one_equity_point_per_tick_plus_close():
    steps = 6
    rep = _replay(steps=steps)
    # One equity point per tick, plus a final session-end point.
    assert len(rep["equity_curve"]) == steps + 1
    # The book flattens at the end: no open positions remain in the summary.
    assert rep["summary"]["open_positions"] == 0


def test_replay_attribution_sums_to_realized():
    rep = _replay()
    by_strat = rep["attribution"]["by_strategy"]
    total = round(sum(b["net_pnl"] for b in by_strat.values()), 2)
    # Per-strategy realized P&L sums to the account realized P&L (closed trades only).
    assert abs(total - rep["summary"]["realized_pnl"]) < 1.0


def test_replay_clock_tick_count():
    ticks = list(ReplayClock(START, steps=5, cadence_s=3600).ticks())
    assert len(ticks) == 5
    assert ticks[0] == START
    assert ticks == sorted(ticks)  # ordered


def test_market_hours_gating():
    # Saturday -> closed.
    sat = datetime(2026, 6, 20, 12, 0, tzinfo=IST)
    assert is_market_open(sat) is False
    # Weekday inside the session -> open; after close -> closed.
    fri_open = datetime(2026, 6, 19, 10, 0, tzinfo=IST)
    fri_after = datetime(2026, 6, 19, 18, 0, tzinfo=IST)
    assert is_market_open(fri_open) is True
    assert is_market_open(fri_after) is False
    assert LiveClock(60).cadence_s == 60
