"""Live market-hours simulation as a background asyncio task.

Ticks via ``LiveClock`` + ``LiveChainSource`` while the IST market is open, wires the calibration
ledger, records every tick (``TickRecorder``) for exact future replay, publishes ``PAPER_PNL`` to the
``EventBus`` for the UI stream, persists equity incrementally via a TASK-OWNED session (not a request
session), and auto-flattens at market close. Never blocks the event loop: the REST chain fetch and the
CPU-bound ``run_tick`` both go to the threadpool.

``force_open`` ticks regardless of market hours (so the live loop can be demoed on real data outside
09:15-15:30 IST); it is clearly flagged in the run params/UI as a demo, not a real session.
"""

from __future__ import annotations

import asyncio

from starlette.concurrency import run_in_threadpool

from ..db.engine import get_sessionmaker
from ..ledger.ledger import CalibrationLedger
from ..obs import log
from ..paper import repo as prepo
from ..paper.account import PaperBook
from ..store.bars import BarStore
from ..store.timeseries import SnapshotStore
from ..strategy import SignalContext
from ..tips.calibration import record_tip
from ..tips.eod import tip_source_for
from ..tips.predict import predict_for_chain
from ..tips.resolve import terminal_payoff
from ..tips.series import build_series_block
from ..tips.store import IssuedTipStore, TipValidationStore
from ..tips.types import HEADLINE
from .chain_source import LiveChainSource
from .clock import LiveClock, is_market_open
from .eventbus import PAPER_PNL, PREDICTION, TIP_RESOLVED, get_bus
from .realtime import RealtimeEngine
from .recorder import TickRecorder
from .run_registry import get_registry


def _tip_pass(chain, source, equity, vstore, series=None):
    """Build the live prediction (always present) + gated tips for one chain. Threadpool-safe.

    Returns ``(prediction_dict, tips, owner_view)``. ``owner_view`` is the Phase-4 emission interlock
    (personal mode on AND Gate-0 passed); the prediction is serialized accordingly and the caller uses
    it to decide whether the sized tips may be PUBLISHED (recording to the ledger is unconditional).

    ``series`` is the optional time-series block (closes/bars/flow) so momentum & flow factors fire on
    the live tick; None => the legacy chain-only read."""
    from ..gating import personal_mode_armed

    owner_view = personal_mode_armed(vstore)
    # Compute the (expensive) owner risk overlay only when the owner surface is armed — the public
    # serialization strips it anyway, so there's no point paying for it otherwise.
    from ..tips.meta_store import get_meta_label

    _ctx, _bucket, _signals, pred, tips = predict_for_chain(
        chain, source=source, equity=equity, validation_store=vstore, with_risk=owner_view,
        series=series, meta_label=get_meta_label())
    return pred.to_dict(owner=owner_view), tips, owner_view


def _resolve_pass(istore, ledger, underlying, ts, owner_view, bus, run_id) -> int:
    """Phase-5 opportunistic resolution: settle same-day-due tips against a PUBLISHED close only
    (spot fallback OFF → causal), persist the outcome, and publish a wall-gated TIP_RESOLVED event.
    Intraday ticks before the close is published resolve nothing. Idempotent (``due_unresolved``
    filters resolved). Best-effort — the caller swallows failures."""
    from .closes import realized_closes_for

    day = ts[:10]
    level = realized_closes_for([underlying], day, allow_spot_fallback=False).get(underlying.upper())
    if level is None:
        return 0
    n = 0
    for d in istore.due_unresolved(underlying, day):
        gross = terminal_payoff(d["legs"], int(d["lot_size"]), float(level))
        net = gross - float(d["round_trip_cost"] or 0.0)
        outcome = int(net > 0)
        ml = float(d.get("max_loss") or 0.0)
        ret = net / ml if ml > 0 else 0.0
        fid = d.get("ledger_forecast_id")
        if fid:
            try:
                ledger.resolve(fid, 1.0 if outcome else -1.0, resolved_ts=ts)
            except KeyError:  # forecast not in this ledger — skip
                pass
        istore.mark_resolved(d["tip_id"], outcome, ts, net_pnl=net, ret=ret)
        bus.publish(TIP_RESOLVED, {  # sized fields walled behind owner_view
            "run_id": run_id, "ts": ts, "underlying": underlying, "tip_id": d["tip_id"],
            "outcome": outcome, "net_pnl": round(net, 2) if owner_view else None,
            "ret": round(ret, 4) if owner_view else None})
        n += 1
    return n


async def run_live(
    run_id: int,
    user_id: int,
    account_id: int,
    underlyings,
    *,
    cadence_s: int = 60,
    gen_cfg=None,
    governor=None,
    capital=None,
    source=None,
    force_open: bool = False,
    max_ticks: int = 0,
    record_tips: bool = True,
) -> None:
    reg = get_registry()
    handle = reg.get(run_id)
    bus = get_bus()
    book = PaperBook(starting_capital=capital)
    ledger = CalibrationLedger()
    engine = RealtimeEngine(book=book, governor=governor, ledger=ledger, gen_cfg=gen_cfg)
    src = LiveChainSource(source)
    clock = LiveClock(cadence_s=cadence_s)
    recorder = TickRecorder()
    smaker = get_sessionmaker()
    unds = [u.upper() for u in underlyings]
    conn_name = getattr(src._conn, "name", "live")
    # Tips/predictions ride the same live loop: each tick also emits the per-underlying prediction
    # (never empty) and persists any gated tip. Stores are task-owned and closed in finally.
    tip_vstore = TipValidationStore() if record_tips else None
    tip_istore = IssuedTipStore() if record_tips else None
    # Shared read handles for the momentum time-series block (closes from Yahoo cache + recorded
    # bars/flow). Task-owned, closed in finally. Same-process DuckDB handles to the recorder's store
    # are safe; building the block per tick is cheap (small cached reads).
    bar_store = BarStore() if record_tips else None
    snap_store = SnapshotStore() if record_tips else None
    tip_src = tip_source_for(conn_name)

    ticks = 0
    status = "done"
    note = ""
    last_ctx: dict[str, SignalContext] = {}
    try:
        # First-tick gate: if the market is closed and we're not forcing, finish cleanly with a note.
        if not force_open and not is_market_open(clock.now_ist()):
            note = "market closed — live mode runs 09:15-15:30 IST (use Today mode now)."
            status = "done"
        else:
            while True:
                if handle is not None and handle.stop_event.is_set():
                    status = "stopped"
                    break
                ts = clock.tick() or (clock.now_ist().isoformat() if force_open else None)
                if ts is None:
                    note = "market closed"
                    break
                for u in unds:
                    try:
                        chain = await run_in_threadpool(src.chain, u)
                    except Exception as e:  # noqa: BLE001 - one broker hiccup must not kill the run
                        log.warning("live_chain_fetch_failed", run_id=run_id, underlying=u, error=str(e)[:200])
                        continue
                    ctx = SignalContext(chain, iv_history=list(engine.iv_history.get(u, [])), source="live")
                    await run_in_threadpool(engine.run_tick, ctx, ts)
                    last_ctx[u] = ctx
                    try:
                        recorder.record_chain(chain, source=conn_name)
                    except Exception:  # noqa: BLE001 - recording is best-effort
                        pass
                    if record_tips:
                        try:
                            series = await run_in_threadpool(
                                build_series_block, u, bar_store=bar_store, snap_store=snap_store)
                            pred, tip_list, owner_view = await run_in_threadpool(
                                _tip_pass, chain, tip_src, book.starting_capital, tip_vstore, series)
                            for tp in tip_list:  # recording is internal measurement — always full
                                record_tip(ledger, tp, spot=pred["spot"], forward=ctx.forward)
                                tip_istore.record(tp)
                            # Egress is walled: sized tips publish only when the owner surface is armed.
                            bus.publish(PREDICTION, {"run_id": run_id, "ts": ts, "underlying": u,
                                                     "prediction": pred,
                                                     "tips": [t.to_dict() for t in tip_list] if owner_view else []})
                            # Coverage (Phase 5): one engine pass — did it speak, and at what tier?
                            spoke = bool(tip_list)
                            tip_istore.bump_coverage(
                                ts[:10], u, tip_src, spoke=spoke, actionable=spoke,
                                watch=any(getattr(t, "tier", "") != HEADLINE for t in tip_list),
                                headline=any(getattr(t, "tier", "") == HEADLINE for t in tip_list),
                                conviction=float(pred.get("confidence") or 0.0) if spoke else None)
                            # Opportunistic resolution: settle same-day-due tips at the published close.
                            _resolve_pass(tip_istore, ledger, u, ts, owner_view, bus, run_id)
                        except Exception as e:  # noqa: BLE001 - tips are best-effort on a live tick
                            log.warning("live_tip_pass_failed", run_id=run_id, underlying=u, error=str(e)[:200])
                ep = book.record_equity_point(ts)
                bus.publish(PAPER_PNL, {
                    "run_id": run_id, "ts": ts, "equity": ep.equity, "cash": ep.cash,
                    "unrealized_pnl": ep.unrealized_pnl, "realized_pnl": ep.realized_pnl,
                    "open_positions": ep.open_positions, "drawdown": ep.drawdown,
                })
                async with smaker() as session:
                    await prepo.insert_equity_point(
                        session, user_id=user_id, account_id=account_id, run_id=run_id, ep=ep
                    )
                    await session.commit()
                ticks += 1
                if max_ticks and ticks >= max_ticks:
                    break
                await asyncio.sleep(cadence_s)

        # Session end: flatten any open positions at the last seen chain and resolve convictions.
        for ctx in last_ctx.values():
            book.flatten(ctx, reason="market_close")
        engine._resolve_new_closed()
    except asyncio.CancelledError:
        status = "stopped"
        raise
    except Exception as e:  # noqa: BLE001 - a live run must never crash the worker silently
        status = "error"
        note = f"{type(e).__name__}: {e}"[:200]
        log.warning("live_run_error", run_id=run_id, error=note)
    finally:
        try:
            async with smaker() as session:
                run = await prepo.get_run(session, user_id, run_id)
                if run is not None:
                    for pos in book.closed:
                        await prepo.insert_position(
                            session, user_id=user_id, account_id=account_id, run_id=run_id,
                            recommendation_id=None, pos=pos,
                        )
                    stats = {
                        "net_pnl": round(book.equity() - book.starting_capital, 2),
                        "ending_equity": round(book.equity(), 2),
                        "ticks": ticks, "open_positions": len(book.open), "note": note,
                    }
                    await prepo.set_run_status(session, run, status, stats=stats, ended=True)
                    await session.commit()
        except Exception as e:  # noqa: BLE001
            log.warning("live_run_finalize_failed", run_id=run_id, error=str(e)[:200])
        bus.publish(PAPER_PNL, {"run_id": run_id, "status": status, "done": True, "note": note})
        try:
            recorder.close()
        except Exception:  # noqa: BLE001
            pass
        for _store in (bar_store, snap_store):
            try:
                if _store is not None:
                    _store.close()
            except Exception:  # noqa: BLE001
                pass
        ledger.close()
        for _s in (tip_vstore, tip_istore):
            if _s is not None:
                try:
                    _s.close()
                except Exception:  # noqa: BLE001
                    pass
        reg.discard(run_id)
        log.info("live_run_finished", run_id=run_id, status=status, ticks=ticks)
