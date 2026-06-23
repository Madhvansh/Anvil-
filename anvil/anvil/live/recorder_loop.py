"""Always-on intraday option-chain recorder — the unattended poller behind ``anvil record run``.

Per-strike OI/IV history is **unbuyable**: brokers don't sell it, so every market minute not recorded
is lost forever. The recorder + snapshot store already exist (``TickRecorder``, ``SnapshotStore``);
this is the standalone market-hours loop that drives them on a schedule (Windows Task Scheduler)
without the REST server or a paper run.

  * **Holiday-aware** — gates on ``clock.is_market_open`` (now backed by the trading calendar).
  * **Token-aware** — when no source is forced it resolves via ``pick_connector``; if no broker holds
    a live token it logs and waits rather than recording demo data as if it were live.
  * **Resilient** — one underlying erroring doesn't sink the others; graceful SIGINT/SIGTERM shutdown.

Injectables (``connector``/``now``/``sleep``/``recorder``) keep it unit-testable fully offline.
"""

from __future__ import annotations

import signal
import time as _time
from datetime import datetime

from ..ingest import get_connector
from ..ingest.source import pick_connector
from .clock import IST, MARKET_CLOSE, is_market_open
from .recorder import TickRecorder
from .trading_calendar import is_trading_day


def _resolve(source, connector):
    """Return ``(connector, mode, name)``. Explicit ``connector``/``source`` are honoured as-is;
    otherwise auto-resolve to the best LIVE broker (demo if none, flagged mode='demo')."""
    if connector is not None:
        return connector, "live", getattr(connector, "name", source or "live")
    if source:
        conn = get_connector(source)
        return conn, ("demo" if source.lower() == "demo" else "live"), getattr(conn, "name", source)
    conn, status = pick_connector()
    return conn, status.mode, status.resolved


def run_recorder(
    underlyings, *, cadence_s: int = 60, source: str | None = None, once: bool = False,
    force_open: bool = False, max_ticks: int = 0, recorder: TickRecorder | None = None,
    connector=None, now=None, sleep=None,
) -> dict:
    """Poll the live chain for each underlying every ``cadence_s`` while the IST market is open and
    record each snapshot. ``once`` records a single cycle then returns (also handy as a cron-per-minute
    body). Returns a summary dict."""
    unds = [u.strip().upper() for u in (
        underlyings if isinstance(underlyings, (list, tuple)) else str(underlyings).split(","))]
    now = now or (lambda: datetime.now(IST))
    sleep = sleep or _time.sleep
    rec = recorder or TickRecorder()
    owns = recorder is None

    stop = {"flag": False}
    installed = []
    for signame in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, signame, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, lambda *_a: stop.__setitem__("flag", True))
            installed.append(sig)
        except (ValueError, OSError):  # not in the main thread (e.g. tests) — skip
            pass

    ticks = recorded = errors = 0
    last_ts = None
    try:
        while not stop["flag"]:
            ts = now()
            if not force_open and not is_market_open(ts):
                if once:
                    return {"status": "closed", "reason": "market closed", "ticks": 0,
                            "recorded": 0, "errors": 0, "last_ts": None}
                # Past the close or a non-trading day → exit (the scheduler relaunches tomorrow);
                # before the open on a trading day → wait for the bell.
                after_close = ts.timetz().replace(tzinfo=None) > MARKET_CLOSE
                if after_close or not is_trading_day(ts.date()):
                    break
                sleep(cadence_s)
                continue

            conn, mode, name = _resolve(source, connector)
            if mode != "live" and not (source and source.lower() == "demo") and connector is None:
                # No live token — don't record demo data as live history; wait for a re-auth.
                print(f"  [record] no live broker connected — waiting (src={name})")
                if once:
                    return {"status": "no_live_source", "ticks": 0, "recorded": 0,
                            "errors": 0, "last_ts": None}
                sleep(cadence_s)
                continue

            for u in unds:
                try:
                    chain = conn.get_chain(u)
                    rec.record_chain(chain, source=name)
                    recorded += 1
                except Exception as e:  # noqa: BLE001 - one underlying down must not sink the loop
                    errors += 1
                    print(f"  [record] {u} error: {str(e)[:120]}")
            ticks += 1
            last_ts = ts.isoformat()
            print(f"  [record] tick {ticks} @ {last_ts} recorded={recorded} errors={errors} src={name}")
            if once or (max_ticks and ticks >= max_ticks):
                break
            sleep(cadence_s)
    except KeyboardInterrupt:  # pragma: no cover - operator Ctrl-C
        pass
    finally:
        if owns:
            try:
                rec.close()
            except Exception:  # noqa: BLE001
                pass
        for sig in installed:
            try:
                signal.signal(sig, signal.SIG_DFL)
            except (ValueError, OSError):  # pragma: no cover
                pass
    return {"status": "ok", "ticks": ticks, "recorded": recorded, "errors": errors, "last_ts": last_ts}
