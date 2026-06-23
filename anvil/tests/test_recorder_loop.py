"""Phase 1 — the always-on recorder loop: market-hours gating, demo --once record, resilience."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from anvil.ingest.demo import DemoConnector
from anvil.live.recorder import TickRecorder
from anvil.live.recorder_loop import run_recorder
from anvil.store import SnapshotStore

IST = timezone(timedelta(hours=5, minutes=30))


class _FakeRecorder:
    def __init__(self):
        self.count = 0

    def record_chain(self, chain, source):
        self.count += 1
        return f"snap-{self.count}"

    def close(self):
        pass


class _FakeConn:
    name = "fake"

    def get_chain(self, underlying, expiry=None):
        return {"underlying": underlying}  # opaque; the fake recorder doesn't analyze it


def test_market_closed_records_nothing():
    closed = datetime(2025, 8, 15, 10, 0, tzinfo=IST)  # Independence Day → holiday
    res = run_recorder(["NIFTY"], once=True, now=lambda: closed, recorder=_FakeRecorder())
    assert res["status"] == "closed" and res["recorded"] == 0


def test_force_open_once_records_every_underlying():
    rec = _FakeRecorder()
    res = run_recorder(["NIFTY", "BANKNIFTY", "SENSEX"], once=True, force_open=True,
                       connector=_FakeConn(), recorder=rec)
    assert res["recorded"] == 3 and rec.count == 3 and res["status"] == "ok"


def test_max_ticks_bounds_the_loop():
    calls = {"n": 0}
    res = run_recorder(["NIFTY"], force_open=True, max_ticks=4, connector=_FakeConn(),
                       recorder=_FakeRecorder(), sleep=lambda _s: calls.__setitem__("n", calls["n"] + 1))
    assert res["ticks"] == 4 and res["recorded"] == 4


def test_one_underlying_error_does_not_sink_the_loop():
    class _Flaky:
        name = "flaky"

        def get_chain(self, underlying, expiry=None):
            if underlying == "BANKNIFTY":
                raise RuntimeError("boom")
            return {"underlying": underlying}

    res = run_recorder(["NIFTY", "BANKNIFTY"], once=True, force_open=True,
                       connector=_Flaky(), recorder=_FakeRecorder())
    assert res["recorded"] == 1 and res["errors"] == 1


def test_real_demo_path_writes_a_snapshot(tmp_path):
    store = SnapshotStore(path=str(tmp_path / "snap.duckdb"))
    rec = TickRecorder(store=store)
    try:
        res = run_recorder(["NIFTY"], once=True, force_open=True, connector=DemoConnector(), recorder=rec)
        assert res["recorded"] == 1
        rows = store.con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        chain_rows = store.con.execute("SELECT COUNT(*) FROM chain_rows").fetchone()[0]
        assert rows == 1 and chain_rows > 0  # snapshot + per-strike OI/IV persisted
    finally:
        store.close()
