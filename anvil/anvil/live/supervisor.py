"""LiveSupervisor — the one-process orchestrator behind ``anvil go-live`` (Wave 0, the unification
keystone).

It runs the WHOLE live cockpit in a single process by owning a few asyncio background tasks, each
REUSING the same standalone functions the CLI jobs use (no fork):
  * **cockpit loop** — every cadence while the market is open: fetch each chain, record it, build the
    momentum series block, run ``predict_for_chain`` (so momentum/flow factors fire), record the tip to
    the moat, and publish a ``PREDICTION`` event for the live UI stream;
  * **nightly loop** — once per trading day after the configured IST cutoff: ``cycle.run_daily_cycle``
    with auto-resolution (the moat clock + tips revalidation + calibration refit);
  * **heartbeat** — publishes a ``COCKPIT_STATUS`` snapshot (mode/last-run/market-open) so the header
    can show DEMO vs LIVE + freshness.

Single-flight (``start`` is a no-op if already running), clean cancel on ``stop``, all CPU/DuckDB work
in the threadpool so the event loop never blocks. Stores are task-owned (opened in ``start``, closed in
``stop``) or injected for tests. ``force_open`` ticks regardless of market hours (demo outside 09:15-15:30
IST). Injectable ``connector``/``now``/``sleep``/``bus`` keep it unit-testable fully offline.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from starlette.concurrency import run_in_threadpool

from ..config import SETTINGS
from ..gating import personal_mode_armed
from ..ingest.base import attach_parity_forward
from ..ledger.ledger import CalibrationLedger
from ..store.bars import BarStore
from ..store.timeseries import SnapshotStore
from ..tips.calibration import record_tip
from ..tips.eod import tip_source_for
from ..tips.meta_store import get_meta_label
from ..tips.predict import predict_for_chain
from ..tips.series import build_series_block
from ..tips.store import IssuedTipStore, TipValidationStore
from .clock import IST, is_market_open
from .cycle import run_daily_cycle
from .eventbus import COCKPIT_STATUS, PREDICTION, get_bus
from .recorder import TickRecorder


def nightly_due(now: datetime, cutoff_hhmm: str, last_done_day: str | None) -> bool:
    """True iff the nightly moat clock should run now: a trading day, past the HH:MM IST cutoff, and not
    already run today. Pure (no I/O beyond the holiday calendar) → directly testable."""
    from .trading_calendar import is_trading_day

    day = now.date().isoformat()
    if last_done_day == day or not is_trading_day(now.date()):
        return False
    try:
        hh, mm = (int(x) for x in cutoff_hhmm.split(":"))
    except (ValueError, AttributeError):
        hh, mm = 15, 40
    return (now.hour, now.minute) >= (hh, mm)


def cockpit_predict_once(
    conn, underlyings, *, src, bars, snaps, vstore, ledger, istore, recorder, bus, ts, equity,
) -> int:
    """One cockpit cadence: per underlying fetch chain → record → predict (WITH momentum series) →
    record the tip to the moat → publish a wall-gated ``PREDICTION``. Best-effort per underlying (one
    failure never sinks the others). Returns the number of underlyings published."""
    published = 0
    name = getattr(conn, "name", "live")
    for u in underlyings:
        try:
            chain = attach_parity_forward(conn.get_chain(u))
        except Exception:  # noqa: BLE001 - one broker hiccup must not kill the cadence
            continue
        if recorder is not None:
            try:
                recorder.record_chain(chain, source=name)
            except Exception:  # noqa: BLE001 - recording is best-effort
                pass
        try:
            series = build_series_block(u, bar_store=bars, snap_store=snaps)
            owner = personal_mode_armed(vstore)
            ctx, _bucket, _signals, pred, tips = predict_for_chain(
                chain, source=src, equity=equity, validation_store=vstore, with_risk=owner, series=series,
                meta_label=get_meta_label())
            for tp in tips:  # recording is internal measurement — always full (the moat accrues)
                if ledger is not None:
                    record_tip(ledger, tp, spot=ctx.spot, forward=ctx.forward)
                if istore is not None:
                    istore.record(tp)
            bus.publish(PREDICTION, {
                "ts": ts, "underlying": u, "source": "cockpit",
                "prediction": pred.to_dict(owner=owner),
                "tips": [t.to_dict() for t in tips] if owner else [],
            })
            published += 1
        except Exception:  # noqa: BLE001 - predictions are best-effort per tick
            continue
    return published


class LiveSupervisor:
    def __init__(
        self, *, underlyings=None, recorder_cadence_s=None, cockpit_cadence_s=None, nightly_ist=None,
        heartbeat_s: int = 15, cockpit_enabled: bool = True, force_open: bool = False, equity=None,
        connector=None, now=None, sleep=None, bus=None,
        recorder=None, bars=None, snaps=None, vstore=None, istore=None, ledger=None,
    ):
        self.underlyings = [u.strip().upper() for u in (
            underlyings if underlyings is not None else SETTINGS.cockpit_underlyings.split(",")) if u and u.strip()]
        self.recorder_cadence_s = recorder_cadence_s or SETTINGS.recorder_cadence_s
        self.cockpit_cadence_s = cockpit_cadence_s or SETTINGS.cockpit_cadence_s
        self.nightly_ist = nightly_ist or SETTINGS.nightly_cycle_ist
        self.heartbeat_s = heartbeat_s
        self.cockpit_enabled = cockpit_enabled
        self.force_open = force_open
        self.equity = equity if equity is not None else SETTINGS.paper_starting_capital
        self._connector = connector
        self._now = now or (lambda: datetime.now(IST))
        self._sleep = sleep or asyncio.sleep
        self.bus = bus or get_bus()

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._last = {"recorder": None, "cockpit": None, "nightly": None, "heartbeat": None}
        self._nightly_done_day: str | None = None
        self._mode: str | None = None
        self._source: str | None = None

        # Stores: injected (tests) or opened in start().
        self._recorder, self._bars, self._snaps = recorder, bars, snaps
        self._vstore, self._istore, self._ledger = vstore, istore, ledger
        self._owns_stores = False

    # --- connector / market gate ------------------------------------------- #
    def _resolve_conn(self):
        if self._connector is not None:
            self._mode, self._source = "live", getattr(self._connector, "name", "live")
            return self._connector, self._mode, self._source
        from ..ingest.source import pick_connector

        conn, status = pick_connector()
        self._mode, self._source = status.mode, status.resolved
        return conn, status.mode, status.resolved

    def _is_open(self, now: datetime) -> bool:
        try:
            return self.force_open or is_market_open(now)
        except Exception:  # noqa: BLE001
            return self.force_open

    # --- lifecycle --------------------------------------------------------- #
    async def start(self) -> bool:
        """Start the background tasks. No-op (returns False) if already running (single-flight)."""
        if self._running:
            return False
        self._running = True
        if self._recorder is None and self._bars is None:  # nothing injected → own real stores
            self._owns_stores = True
            self._recorder = TickRecorder()
            self._bars = BarStore()
            self._snaps = SnapshotStore()
            self._vstore = TipValidationStore()
            self._istore = IssuedTipStore()
            self._ledger = CalibrationLedger()
        self._tasks = [
            asyncio.create_task(self._nightly_loop()),
            asyncio.create_task(self._heartbeat_loop()),
        ]
        self._tasks.append(asyncio.create_task(
            self._cockpit_loop() if self.cockpit_enabled else self._recorder_loop()))
        return True

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._owns_stores:
            for s in (self._recorder, self._bars, self._snaps, self._vstore, self._istore, self._ledger):
                try:
                    if s is not None:
                        s.close()
                except Exception:  # noqa: BLE001
                    pass

    def status(self) -> dict:
        return {
            "running": self._running,
            "mode": self._mode,
            "source": self._source,
            "underlyings": self.underlyings,
            "market_open": self._is_open(self._now()),
            "cockpit_enabled": self.cockpit_enabled,
            "force_open": self.force_open,
            "last": dict(self._last),
            "nightly_done_day": self._nightly_done_day,
        }

    # --- loops ------------------------------------------------------------- #
    async def _cockpit_loop(self) -> None:
        while self._running:
            try:
                now = self._now()
                if self._is_open(now):
                    conn, _mode, name = self._resolve_conn()
                    await run_in_threadpool(
                        cockpit_predict_once, conn, self.underlyings, src=tip_source_for(name),
                        bars=self._bars, snaps=self._snaps, vstore=self._vstore, ledger=self._ledger,
                        istore=self._istore, recorder=self._recorder, bus=self.bus,
                        ts=now.isoformat(), equity=self.equity)
                    self._last["cockpit"] = self._last["recorder"] = now.isoformat()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a loop must never die on a transient error
                pass
            await self._sleep(self.cockpit_cadence_s)

    async def _recorder_loop(self) -> None:
        while self._running:
            try:
                now = self._now()
                if self._is_open(now):
                    conn, _mode, name = self._resolve_conn()
                    await run_in_threadpool(self._record_tick, conn, name)
                    self._last["recorder"] = now.isoformat()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await self._sleep(self.recorder_cadence_s)

    def _record_tick(self, conn, name) -> None:
        for u in self.underlyings:
            try:
                self._recorder.record_chain(conn.get_chain(u), source=name)
            except Exception:  # noqa: BLE001
                pass

    async def _nightly_loop(self) -> None:
        while self._running:
            try:
                now = self._now()
                if nightly_due(now, self.nightly_ist, self._nightly_done_day):
                    conn, _mode, _name = self._resolve_conn()
                    await run_in_threadpool(
                        run_daily_cycle, self.underlyings, connector=conn, auto_resolve=True)
                    self._nightly_done_day = now.date().isoformat()
                    self._last["nightly"] = now.isoformat()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await self._sleep(60)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                self._last["heartbeat"] = self._now().isoformat()
                self.bus.publish(COCKPIT_STATUS, self.status())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                pass
            await self._sleep(self.heartbeat_s)


_SUPERVISOR: LiveSupervisor | None = None


def get_supervisor() -> LiveSupervisor | None:
    return _SUPERVISOR


def set_supervisor(sup: LiveSupervisor | None) -> None:
    global _SUPERVISOR
    _SUPERVISOR = sup
