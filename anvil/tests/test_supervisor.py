"""Tests for the Wave-0 LiveSupervisor: nightly-due logic, one cockpit cadence, start/stop lifecycle."""

from __future__ import annotations

import asyncio
from datetime import datetime

import anvil.live.trading_calendar as tcal
import anvil.tips.series as seriesmod
from anvil.ingest import get_connector
from anvil.ledger.ledger import CalibrationLedger
from anvil.live.clock import IST
from anvil.live.supervisor import LiveSupervisor, cockpit_predict_once, nightly_due
from anvil.store.bars import BarStore
from anvil.store.timeseries import SnapshotStore
from anvil.tips.store import IssuedTipStore, TipValidationStore


class _Bus:
    def __init__(self):
        self.events = []

    def publish(self, kind, data):
        self.events.append((kind, data))
        return 1


def test_nightly_due(monkeypatch):
    monkeypatch.setattr(tcal, "is_trading_day", lambda d: True)
    before = datetime(2026, 6, 23, 15, 30, tzinfo=IST)
    after = datetime(2026, 6, 23, 15, 45, tzinfo=IST)
    assert nightly_due(before, "15:40", None) is False        # before cutoff
    assert nightly_due(after, "15:40", None) is True          # after cutoff, not yet run
    assert nightly_due(after, "15:40", "2026-06-23") is False  # already run today
    monkeypatch.setattr(tcal, "is_trading_day", lambda d: False)
    assert nightly_due(after, "15:40", None) is False         # holiday / non-trading day


def _stores(tmp_path):
    return dict(
        bars=BarStore(str(tmp_path / "b.duckdb")),
        snaps=SnapshotStore(str(tmp_path / "s.duckdb")),
        vstore=TipValidationStore(str(tmp_path / "v.duckdb")),
        istore=IssuedTipStore(str(tmp_path / "i.duckdb")),
        ledger=CalibrationLedger(str(tmp_path / "l.duckdb")),
    )


def test_cockpit_predict_once(tmp_path, monkeypatch):
    monkeypatch.setattr(seriesmod.yahoo, "read_cache", lambda sym: [])  # no network
    bus = _Bus()
    st = _stores(tmp_path)
    try:
        n = cockpit_predict_once(
            get_connector("demo"), ["NIFTY", "BANKNIFTY"], src="tip_live",
            recorder=None, bus=bus, ts="2026-06-23T10:00:00+05:30", equity=1_000_000.0, **st)
        assert n == 2
        kinds = [k for k, _ in bus.events]
        assert kinds.count("prediction") == 2
        for _, d in bus.events:                     # public surface → no owner tips leak
            assert d["tips"] == [] and d["prediction"]["underlying"] in ("NIFTY", "BANKNIFTY")
    finally:
        for s in st.values():
            s.close()


def test_supervisor_start_stop_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(seriesmod.yahoo, "read_cache", lambda sym: [])
    bus = _Bus()
    st = _stores(tmp_path)

    async def run():
        state = {"n": 0}

        async def fake_sleep(_s):
            state["n"] += 1
            if state["n"] >= 4:
                sup._running = False           # let a few iterations run, then drain the loops
            await asyncio.sleep(0)

        sup = LiveSupervisor(
            connector=get_connector("demo"), force_open=True, cockpit_enabled=True,
            underlyings=["NIFTY"], heartbeat_s=0, sleep=fake_sleep, bus=bus, recorder=None,
            now=lambda: datetime(2026, 6, 23, 10, 0, tzinfo=IST), **st)
        assert await sup.start() is True
        assert await sup.start() is False        # single-flight
        status = sup.status()
        assert status["running"] and status["underlyings"] == ["NIFTY"] and status["market_open"]
        await asyncio.gather(*sup._tasks, return_exceptions=True)  # loops exit when _running flips
        await sup.stop()

    asyncio.run(run())
    assert any(k == "prediction" for k, _ in bus.events)   # cockpit ran
    assert any(k == "cockpit_status" for k, _ in bus.events)  # heartbeat ran
    for s in st.values():
        s.close()
