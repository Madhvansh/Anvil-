"""Gated paper-trading API — recommendations, runs, positions, trades, equity.

Every route requires login + the PAPER_TRADING flag (``require_paper_trading``) and is PAPER ONLY.
Real placement is intentionally absent here — it stays on the CLI ``order`` + ``AssistedExecutor``
+ OFF ``TRADING_AUTOMATION`` rail. ``replay`` runs a full deterministic mock session (in a
threadpool, since it is CPU-bound) and persists it under a run id.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from ...config import SETTINGS
from ...db.engine import get_session
from ...db.models import User
from ...ingest.base import attach_parity_forward
from ...live.realtime import RealtimeEngine
from ...paper import repo as prepo
from ...paper.account import PaperBook
from ...strategy import SignalContext, generate_candidates
from ..deps import PAPER_DISCLAIMER, get_source, require_paper_trading

router = APIRouter(prefix="/api/paper", tags=["paper"])


def _acct_dict(acct) -> dict:
    return {
        "id": acct.id, "name": acct.name, "starting_capital": acct.starting_capital, "cash": acct.cash,
        "realized_pnl": acct.realized_pnl, "peak_equity": acct.peak_equity, "currency": acct.base_currency,
    }


@router.get("/account")
async def get_account(user: User = Depends(require_paper_trading), session: AsyncSession = Depends(get_session)):
    acct = await prepo.ensure_account(session, user_id=user.id)
    return {"account": _acct_dict(acct), "disclaimer": PAPER_DISCLAIMER}


@router.post("/account/reset")
async def reset_account(
    starting_capital: float = Body(..., embed=True),
    user: User = Depends(require_paper_trading),
    session: AsyncSession = Depends(get_session),
):
    if starting_capital <= 0:
        raise HTTPException(400, "starting_capital must be positive")
    acct = await prepo.ensure_account(session, user_id=user.id)
    await prepo.reset_account(session, acct, starting_capital)
    return {"account": _acct_dict(acct)}


@router.get("/recommendations/{underlying}")
async def recommendations(
    underlying: str,
    user: User = Depends(require_paper_trading),
    session: AsyncSession = Depends(get_session),
):
    """Live, ranked, sized trade candidates with the full decision policy (paper-only)."""
    acct = await prepo.ensure_account(session, user_id=user.id)
    conn = get_source()
    chain = attach_parity_forward(conn.get_chain(underlying))
    ctx = SignalContext(chain, source=conn.name)
    equity = max(acct.cash, acct.starting_capital)
    cands = await run_in_threadpool(generate_candidates, ctx, equity)
    return {
        "underlying": underlying.upper(),
        "spot": ctx.spot,
        "regime": ctx.regime.label,
        "candidates": [c.to_dict() for c in cands],
        "disclaimer": PAPER_DISCLAIMER,
    }


def build_run_config(cfg: dict | None):
    """Per-run tuning knobs -> (capital, GenConfig, RiskGovernor). Missing keys fall back to SETTINGS."""
    from dataclasses import replace

    from ...paper.governor import GovernorConfig, RiskGovernor
    from ...strategy.generate import GenConfig

    cfg = cfg or {}
    capital = float(cfg.get("capital") or SETTINGS.paper_starting_capital)
    gen = GenConfig.from_settings()
    sizing = gen.sizing
    for k in ("risk_fraction", "kelly_fraction", "max_exposure_pct"):
        if cfg.get(k) is not None:
            sizing = replace(sizing, **{k: float(cfg[k])})
    if cfg.get("max_lots_per_underlying") is not None:
        sizing = replace(sizing, max_lots_per_underlying=int(cfg["max_lots_per_underlying"]))
    gen = replace(gen, sizing=sizing)
    if cfg.get("seller_mode") is not None:
        gen = replace(gen, seller_mode=bool(cfg["seller_mode"]))
    if cfg.get("min_conviction") is not None:
        gen = replace(gen, min_conviction=float(cfg["min_conviction"]))
    gcfg = GovernorConfig.from_settings()
    g_over: dict = {}
    if cfg.get("seller_mode") is not None:
        g_over["seller_mode"] = bool(cfg["seller_mode"])
    if cfg.get("max_exposure_pct") is not None:
        g_over["max_exposure_pct"] = float(cfg["max_exposure_pct"])
    if cfg.get("max_open_positions") is not None:
        g_over["max_open_positions"] = int(cfg["max_open_positions"])
    if cfg.get("max_lots_per_underlying") is not None:
        g_over["max_lots_per_underlying"] = int(cfg["max_lots_per_underlying"])
    if g_over:
        gcfg = replace(gcfg, **g_over)
    return capital, gen, RiskGovernor(gcfg)


def _run_replay(book: PaperBook, params: dict, gen_cfg=None, governor=None) -> tuple[RealtimeEngine, dict]:
    eng = RealtimeEngine(book=book, governor=governor, gen_cfg=gen_cfg)
    report = eng.replay(
        params["underlyings"], start_ts=params["start_ts"], expiry=params["expiry"],
        steps=params["steps"], cadence_s=params["cadence_s"], seed=params["seed"], source_label="replay",
    )
    return eng, report


def _run_today(unds, conn, ledger, gen_cfg, governor, capital, interval_min):
    from ...live.realday import run_today

    book = PaperBook(starting_capital=capital)
    eng = RealtimeEngine(book=book, governor=governor, ledger=ledger, gen_cfg=gen_cfg)
    return run_today(eng, unds, conn, ledger=ledger, interval_min=interval_min)


async def _persist_run(session, user, eng, report, *, mode, source, cadence_s, seed, params, replay_from, replay_to):
    acct = await prepo.ensure_account(session, user_id=user.id, starting_capital=eng.book.starting_capital)
    run = await prepo.create_run(
        session, user_id=user.id, account_id=acct.id, mode=mode, underlyings=params["underlyings"],
        cadence_s=cadence_s, source=source, seed=seed, params=params,
        replay_from=replay_from, replay_to=replay_to,
    )
    for pos in eng.book.closed:
        await prepo.insert_position(
            session, user_id=user.id, account_id=acct.id, run_id=run.id, recommendation_id=None, pos=pos
        )
    for ep in eng.book.equity_points:
        await prepo.insert_equity_point(session, user_id=user.id, account_id=acct.id, run_id=run.id, ep=ep)
    stats = {**report["summary"], "win_rate": report["trades"]["win_rate"], "max_drawdown": report["risk"]["max_drawdown"]}
    await prepo.set_run_status(session, run, "done", stats=stats, ended=True)
    return run.id


@router.post("/runs")
async def start_replay_run(
    body: dict | None = Body(default=None),
    user: User = Depends(require_paper_trading),
    session: AsyncSession = Depends(get_session),
):
    """Start a simulation run and persist it. ``mode``: ``replay`` (synthetic, default) or ``today``
    (the REAL intraday trading day, graded against the real close). Returns the effectiveness report;
    ``today`` also attaches a ``prediction_scorecard``. A per-run ``config`` object tunes capital, risk,
    Kelly, exposure, seller-mode, and conviction."""
    from datetime import date, timedelta

    body = body or {}
    mode = (body.get("mode") or "replay").lower()
    unds = [u.strip().upper() for u in (body.get("underlyings") or ["NIFTY"])]
    capital, gen_cfg, governor = build_run_config(body.get("config"))

    if mode == "today":
        from ...ledger.ledger import CalibrationLedger

        conn = get_source()
        interval = int(body.get("interval") or 15)
        ledger = CalibrationLedger()
        try:
            eng, report = await run_in_threadpool(
                _run_today, unds, conn, ledger, gen_cfg, governor, capital, interval
            )
        finally:
            ledger.close()
        params = {"underlyings": unds, "interval_min": interval, "source": getattr(conn, "name", "demo"),
                  "config": body.get("config") or {}}
        report["run_id"] = await _persist_run(
            session, user, eng, report, mode="today", source=getattr(conn, "name", "demo"),
            cadence_s=interval * 60, seed=None, params=params,
            replay_from=report["meta"].get("start_ts"), replay_to=report["meta"].get("end_ts"),
        )
        return report

    if mode == "live":
        from ...live.live_runner import run_live
        from ...live.run_registry import get_registry

        conn = get_source()
        cadence = max(int(body.get("cadence_s") or 60), 15)
        force_open = bool((body.get("config") or {}).get("force_open"))
        acct = await prepo.ensure_account(session, user_id=user.id, starting_capital=capital)
        params = {"underlyings": unds, "cadence_s": cadence, "source": getattr(conn, "name", "demo"),
                  "config": body.get("config") or {}, "force_open": force_open}
        run = await prepo.create_run(
            session, user_id=user.id, account_id=acct.id, mode="live", underlyings=unds,
            cadence_s=cadence, source=getattr(conn, "name", "demo"), seed=None, params=params,
        )
        await session.commit()  # make the run row visible to the background task before it starts
        handle = get_registry().create(run.id)
        handle.task = asyncio.create_task(run_live(
            run.id, user.id, acct.id, unds, cadence_s=cadence, gen_cfg=gen_cfg, governor=governor,
            capital=capital, source=getattr(conn, "name", None), force_open=force_open,
        ))
        return {"run_id": run.id, "status": "running", "mode": "live"}

    # ----- default: synthetic deterministic replay -----
    today = date.today()
    start_ts = body.get("start_ts") or f"{today.isoformat()}T03:45:00+00:00"
    expiry = body.get("expiry")
    if not expiry:
        d = today + timedelta(days=1)
        while d.weekday() != 3:
            d += timedelta(days=1)
        expiry = d.isoformat()
    params = {
        "underlyings": unds, "start_ts": start_ts, "expiry": expiry,
        "steps": int(body.get("steps", 20)), "cadence_s": int(body.get("cadence_s", 7200)),
        "seed": int(body.get("seed", 7)), "source": "replay", "config": body.get("config") or {},
    }
    book = PaperBook(starting_capital=capital)
    eng, report = await run_in_threadpool(_run_replay, book, params, gen_cfg, governor)
    report["run_id"] = await _persist_run(
        session, user, eng, report, mode="replay", source="replay", cadence_s=params["cadence_s"],
        seed=params["seed"], params=params, replay_from=start_ts, replay_to=expiry,
    )
    return report


@router.get("/runs")
async def list_runs(user: User = Depends(require_paper_trading), session: AsyncSession = Depends(get_session)):
    runs = await prepo.list_runs(session, user.id)
    return [{"id": r.id, "mode": r.mode, "status": r.status, "underlyings": r.underlyings,
             "started_at": r.started_at.isoformat() if r.started_at else None, "stats": r.stats} for r in runs]


@router.get("/runs/{run_id}")
async def get_run(run_id: int, user: User = Depends(require_paper_trading), session: AsyncSession = Depends(get_session)):
    run = await prepo.get_run(session, user.id, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    return {"id": run.id, "mode": run.mode, "status": run.status, "underlyings": run.underlyings,
            "params": run.params, "stats": run.stats}


@router.post("/runs/{run_id}/stop")
async def stop_run(run_id: int, user: User = Depends(require_paper_trading), session: AsyncSession = Depends(get_session)):
    """Signal a live run to stop (flatten + finish). Idempotent."""
    from ...live.run_registry import get_registry

    run = await prepo.get_run(session, user.id, run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    get_registry().stop(run_id)
    return {"run_id": run_id, "status": "stopping"}


@router.get("/runs/{run_id}/stream")
async def stream_run(run_id: int, user: User = Depends(require_paper_trading), session: AsyncSession = Depends(get_session)):
    """Server-Sent Events stream of a live run's PAPER_PNL ticks (equity/P&L). Ends on the run's
    'done' event. The PWA service worker must NOT cache this path (see vite.config.ts NetworkOnly)."""
    from ...live.eventbus import get_bus

    run = await prepo.get_run(session, user.id, run_id)
    if run is None:
        raise HTTPException(404, "run not found")

    async def gen():
        bus = get_bus()
        q = bus.subscribe()
        try:
            yield ": connected\n\n"
            # Race guard: if the run already finished (e.g. market closed -> instant done) before the
            # client connected, emit the terminal state now instead of hanging on an idle stream.
            if run.status in ("done", "stopped", "error"):
                note = (run.stats or {}).get("note", "") if isinstance(run.stats, dict) else ""
                yield f"data: {json.dumps({'run_id': run_id, 'done': True, 'status': run.status, 'note': note})}\n\n"
                return
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"  # keep idle proxies from dropping the stream
                    continue
                if evt.get("run_id") != run_id:
                    continue
                yield f"data: {json.dumps(evt)}\n\n"
                if evt.get("done"):
                    break
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@router.get("/runs/{run_id}/equity-curve")
async def equity_curve(run_id: int, user: User = Depends(require_paper_trading), session: AsyncSession = Depends(get_session)):
    pts = await prepo.list_equity_curve(session, user.id, run_id)
    return [{"ts": p.ts.isoformat(), "equity": p.equity, "cash": p.cash, "unrealized_pnl": p.unrealized_pnl,
             "realized_pnl": p.realized_pnl, "drawdown": p.drawdown, "open_positions": p.open_positions} for p in pts]


@router.get("/positions")
async def positions(
    status: str | None = Query(default=None),
    user: User = Depends(require_paper_trading),
    session: AsyncSession = Depends(get_session),
):
    rows = await prepo.list_positions(session, user.id, status=status)
    return [{"id": p.id, "run_id": p.run_id, "underlying": p.underlying, "strategy": p.strategy,
             "direction": p.direction, "status": p.status, "units": p.units, "legs": p.legs,
             "entry_value": p.entry_value, "max_loss": p.max_loss, "max_profit": p.max_profit,
             "realized_pnl": p.realized_pnl, "unrealized_pnl": p.unrealized_pnl, "close_reason": p.close_reason,
             "conviction": p.conviction, "opened_at": p.opened_at.isoformat() if p.opened_at else None} for p in rows]


@router.get("/trades")
async def trades(
    position_id: int | None = Query(default=None),
    user: User = Depends(require_paper_trading),
    session: AsyncSession = Depends(get_session),
):
    fills = await prepo.list_fills(session, user.id, position_id=position_id)
    return [{"id": f.id, "position_id": f.position_id, "ts": f.ts.isoformat(), "symbol": f.symbol,
             "side": f.side, "lots": f.lots, "qty": f.qty, "fill_price": f.fill_price, "slippage": f.slippage,
             "charges": f.charges, "kind": f.kind} for f in fills]
