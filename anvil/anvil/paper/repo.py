"""Async persistence for the paper-trading subsystem.

Translates between the in-memory simulator state (``anvil/paper/state.py``) and the ``paper_*``
ORM rows. Follows the repo convention in ``db/repo.py``: take an ``AsyncSession`` and flush (not
commit); the request-scoped session commits once. Every row is user-scoped.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import SETTINGS
from ..db.models import (
    PaperAccount,
    PaperEquityPoint,
    PaperFill,
    PaperPositionRow,
    PaperRecommendation,
    PaperRun,
)
from .state import EquityPoint, Fill, PaperPosition


def _dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s + "T00:00:00")
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def ensure_account(session: AsyncSession, *, user_id: int, starting_capital: float | None = None, name: str = "paper") -> PaperAccount:
    res = await session.execute(select(PaperAccount).where(PaperAccount.user_id == user_id, PaperAccount.name == name))
    acct = res.scalar_one_or_none()
    if acct is None:
        cap = float(starting_capital if starting_capital is not None else SETTINGS.paper_starting_capital)
        acct = PaperAccount(
            user_id=user_id, name=name, starting_capital=cap, cash=cap, realized_pnl=0.0,
            peak_equity=cap, day_start_equity=cap, config={},
        )
        session.add(acct)
        await session.flush()
    return acct


async def reset_account(session: AsyncSession, acct: PaperAccount, starting_capital: float) -> PaperAccount:
    acct.starting_capital = float(starting_capital)
    acct.cash = float(starting_capital)
    acct.realized_pnl = 0.0
    acct.peak_equity = float(starting_capital)
    acct.day_start_equity = float(starting_capital)
    await session.flush()
    return acct


async def get_account(session: AsyncSession, user_id: int, name: str = "paper") -> PaperAccount | None:
    res = await session.execute(select(PaperAccount).where(PaperAccount.user_id == user_id, PaperAccount.name == name))
    return res.scalar_one_or_none()


async def create_run(session: AsyncSession, *, user_id: int, account_id: int, mode: str, underlyings: list[str],
                     cadence_s: int = 60, source: str = "demo", seed: int | None = None,
                     params: dict | None = None, replay_from: str | None = None, replay_to: str | None = None) -> PaperRun:
    run = PaperRun(
        user_id=user_id, account_id=account_id, mode=mode, status="running", underlyings=list(underlyings),
        cadence_s=cadence_s, source=source, seed=seed, params=params or {}, stats={},
        replay_from=replay_from, replay_to=replay_to,
    )
    session.add(run)
    await session.flush()
    return run


async def set_run_status(session: AsyncSession, run: PaperRun, status: str, stats: dict | None = None, ended: bool = False) -> PaperRun:
    run.status = status
    if stats is not None:
        run.stats = stats
    if ended:
        run.ended_at = datetime.now(timezone.utc)
    await session.flush()
    return run


async def get_run(session: AsyncSession, user_id: int, run_id: int) -> PaperRun | None:
    run = await session.get(PaperRun, run_id)
    return run if (run and run.user_id == user_id) else None


async def list_runs(session: AsyncSession, user_id: int, limit: int = 50) -> list[PaperRun]:
    res = await session.execute(
        select(PaperRun).where(PaperRun.user_id == user_id).order_by(PaperRun.id.desc()).limit(limit)
    )
    return list(res.scalars().all())


async def insert_recommendation(session: AsyncSession, *, user_id: int, account_id: int | None, run_id: int | None,
                                cand, ts, status: str = "open") -> PaperRecommendation:
    rec = PaperRecommendation(
        user_id=user_id, account_id=account_id, run_id=run_id, ts=_dt(ts), underlying=cand.underlying,
        strategy=cand.strategy, direction=cand.direction, action=cand.action, edge_prob=cand.edge_prob,
        conviction=cand.conviction, no_trade_score=cand.no_trade_score, max_loss=cand.max_loss,
        max_profit=cand.max_profit, entry_debit_credit=cand.entry_debit_credit, horizon_days=cand.horizon_days,
        decision=cand.to_dict(), status=status,
    )
    session.add(rec)
    await session.flush()
    return rec


async def insert_position(session: AsyncSession, *, user_id: int, account_id: int, run_id: int | None,
                          recommendation_id: int | None, pos: PaperPosition) -> PaperPositionRow:
    row = PaperPositionRow(
        user_id=user_id, account_id=account_id, run_id=run_id, recommendation_id=recommendation_id,
        underlying=pos.underlying, strategy=pos.strategy, direction=pos.direction, opened_at=_dt(pos.opened_at),
        status=pos.status, lot_size=pos.lot_size, units=int(pos.recommendation.get("units", 1)),
        legs=[leg.as_dict() for leg in pos.legs], entry_value=pos.entry_value, max_loss=pos.max_loss,
        max_profit=pos.max_profit, reserved_margin=pos.reserved_margin, mark_value=pos.mark_value,
        unrealized_pnl=pos.unrealized_pnl, realized_pnl=pos.realized_pnl, charges_paid=pos.charges_paid,
        greeks=pos.greeks, exit_rules=pos.exit_rules, conviction=pos.conviction, edge_prob=pos.edge_prob,
        opened_regime=pos.opened_regime, close_reason=pos.close_reason, ledger_forecast_id=pos.ledger_forecast_id,
    )
    session.add(row)
    await session.flush()
    for fill in pos.fills:
        await insert_fill(session, user_id=user_id, account_id=account_id, position_id=row.id, fill=fill)
    return row


async def update_position(session: AsyncSession, row: PaperPositionRow, pos: PaperPosition) -> PaperPositionRow:
    row.status = pos.status
    row.mark_value = pos.mark_value
    row.unrealized_pnl = pos.unrealized_pnl
    row.realized_pnl = pos.realized_pnl
    row.charges_paid = pos.charges_paid
    row.greeks = pos.greeks
    row.close_reason = pos.close_reason
    row.ledger_forecast_id = pos.ledger_forecast_id
    if pos.closed_at:
        row.closed_at = _dt(pos.closed_at)
    await session.flush()
    return row


async def insert_fill(session: AsyncSession, *, user_id: int, account_id: int, position_id: int | None, fill: Fill) -> PaperFill:
    row = PaperFill(
        user_id=user_id, account_id=account_id, position_id=position_id, ts=_dt(fill.ts), symbol=fill.symbol,
        underlying=fill.underlying, instrument_type=fill.instrument_type, strike=fill.strike, expiry=fill.expiry,
        option_type=fill.option_type, side=fill.side, lots=fill.lots, qty=fill.qty, fill_price=fill.fill_price,
        ref_mid=fill.ref_mid, slippage=fill.slippage, charges=fill.charges, kind=fill.kind, status=fill.status,
    )
    session.add(row)
    await session.flush()
    return row


async def insert_equity_point(session: AsyncSession, *, user_id: int, account_id: int, run_id: int, ep: EquityPoint) -> PaperEquityPoint:
    row = PaperEquityPoint(
        user_id=user_id, account_id=account_id, run_id=run_id, ts=_dt(ep.ts), equity=ep.equity, cash=ep.cash,
        unrealized_pnl=ep.unrealized_pnl, realized_pnl=ep.realized_pnl, gross_exposure=ep.gross_exposure,
        net_delta=ep.net_delta, open_positions=ep.open_positions, drawdown=ep.drawdown,
    )
    session.add(row)
    await session.flush()
    return row


async def persist_account(session: AsyncSession, acct: PaperAccount, book) -> PaperAccount:
    acct.cash = book.cash
    acct.realized_pnl = book.realized_pnl
    acct.peak_equity = book.peak_equity
    await session.flush()
    return acct


# --- read paths (API) ---------------------------------------------------------------
async def list_positions(session: AsyncSession, user_id: int, status: str | None = None, limit: int = 200) -> list[PaperPositionRow]:
    q = select(PaperPositionRow).where(PaperPositionRow.user_id == user_id)
    if status:
        q = q.where(PaperPositionRow.status == status)
    res = await session.execute(q.order_by(PaperPositionRow.id.desc()).limit(limit))
    return list(res.scalars().all())


async def get_position(session: AsyncSession, user_id: int, pos_id: int) -> PaperPositionRow | None:
    row = await session.get(PaperPositionRow, pos_id)
    return row if (row and row.user_id == user_id) else None


async def list_fills(session: AsyncSession, user_id: int, position_id: int | None = None, limit: int = 500) -> list[PaperFill]:
    q = select(PaperFill).where(PaperFill.user_id == user_id)
    if position_id is not None:
        q = q.where(PaperFill.position_id == position_id)
    res = await session.execute(q.order_by(PaperFill.id.desc()).limit(limit))
    return list(res.scalars().all())


async def list_equity_curve(session: AsyncSession, user_id: int, run_id: int) -> list[PaperEquityPoint]:
    res = await session.execute(
        select(PaperEquityPoint).where(PaperEquityPoint.user_id == user_id, PaperEquityPoint.run_id == run_id).order_by(PaperEquityPoint.ts)
    )
    return list(res.scalars().all())


async def list_recommendations(session: AsyncSession, user_id: int, run_id: int | None = None, limit: int = 100) -> list[PaperRecommendation]:
    q = select(PaperRecommendation).where(PaperRecommendation.user_id == user_id)
    if run_id is not None:
        q = q.where(PaperRecommendation.run_id == run_id)
    res = await session.execute(q.order_by(PaperRecommendation.id.desc()).limit(limit))
    return list(res.scalars().all())


async def get_recommendation(session: AsyncSession, user_id: int, rec_id: int) -> PaperRecommendation | None:
    row = await session.get(PaperRecommendation, rec_id)
    return row if (row and row.user_id == user_id) else None
