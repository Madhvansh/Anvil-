"""Phase 2 — paper simulator: costs, fills, Risk Governor, position lifecycle, MTM fidelity, and
ORM persistence. Deterministic on the demo connector; no network, no keys."""

from __future__ import annotations

import asyncio

from anvil.config import SETTINGS
from anvil.engine.scenarios import _book_value
from anvil.ingest.demo import build_demo_chain
from anvil.paper import PaperBook, PaperBrokerGateway, RiskGovernor
from anvil.paper import costs, mtm
from anvil.strategy import SignalContext, generate_candidates, TRADE


def _ctx(spot: float = 24000.0) -> SignalContext:
    return SignalContext(build_demo_chain("NIFTY", spot=spot))


def _trade_candidates(ctx, equity):
    return [c for c in generate_candidates(ctx, equity) if c.action == TRADE]


# --- cost model -------------------------------------------------------------
def test_fill_crosses_the_spread():
    assert costs.fill_price("BUY", 100.0, bid=99.0, ask=101.0) == 101.0
    assert costs.fill_price("SELL", 100.0, bid=99.0, ask=101.0) == 99.0
    # No quotes -> mid +/- slippage
    buy = costs.fill_price("BUY", 100.0, slippage_bps=50)  # 0.5%
    assert abs(buy - 100.5) < 1e-6


def test_charges_option_stt_is_sell_side_only():
    sell = costs.charges("SELL", 120.0, 75, "CE")
    buy = costs.charges("BUY", 120.0, 75, "CE")
    assert sell.stt > 0 and buy.stt == 0.0  # STT on options is sell-side premium
    assert buy.stamp > 0 and sell.stamp == 0.0  # stamp on buy-side
    assert sell.total > 0 and buy.total > 0


# --- gateway ----------------------------------------------------------------
def test_gateway_simulates_offline():
    gw = PaperBrokerGateway()
    fill = gw.simulate_fill(side="SELL", qty=75, lots=1, mid=120.0, bid=119.0, ask=121.0,
                            instrument_type="CE", underlying="NIFTY", symbol="NIFTY24000CE")
    assert fill.status == "FILLED_SIMULATED"
    assert fill.fill_price == 119.0  # sell crosses to bid
    assert fill.charges["total"] > 0


# --- lifecycle + reconciliation ---------------------------------------------
def test_open_mtm_close_reconciles_pnl():
    ctx = _ctx()
    book = PaperBook(starting_capital=1_000_000.0)
    gov = RiskGovernor()
    opened = 0
    for cand in _trade_candidates(ctx, book.equity()):
        pos, _ = book.try_open(cand, ctx, gov)
        opened += 1 if pos else 0
    assert opened >= 1
    # While positions are open: equity = cash + sum(mark_value).
    assert abs(book.equity() - (book.cash + sum(p.mark_value for p in book.open))) < 0.01
    # Close everything; with a flat book, equity must equal start + realized P&L exactly.
    for pos in list(book.open):
        book.close_position(pos, ctx, "manual")
    assert not book.open
    assert abs(book.equity() - (book.starting_capital + book.realized_pnl)) < 0.01
    for p in book.closed:
        assert p.realized_pnl == p.realized_pnl  # finite, not NaN


def test_mtm_matches_independent_book_value():
    ctx = _ctx()
    book = PaperBook(starting_capital=1_000_000.0)
    gov = RiskGovernor()
    cand = next(c for c in _trade_candidates(ctx, book.equity()))
    pos, _ = book.try_open(cand, ctx, gov)
    assert pos is not None
    # The book's mark must equal an independent scenarios._book_value recompute (one pricing path).
    positions = mtm.legs_to_positions(pos, ctx.chain)
    independent = _book_value(positions, ctx.chain, 0.0, 0.0, 0.0, SETTINGS.risk_free_rate)
    assert abs(pos.mark_value - round(independent, 2)) < 0.01


# --- risk governor ----------------------------------------------------------
def test_governor_enforces_exposure_invariant():
    ctx = _ctx()
    book = PaperBook(starting_capital=1_000_000.0)
    gov = RiskGovernor()
    for cand in _trade_candidates(ctx, book.equity()):
        book.try_open(cand, ctx, gov)
    # No matter what was opened, gross exposure never exceeds the cap and buying power stays >= 0.
    assert book.gross_exposure() <= SETTINGS.paper_max_exposure_pct * book.equity() + 1.0
    assert book.buying_power() >= -1.0


def test_governor_rejects_naked_without_seller_mode():
    from anvil.paper.governor import GovernorConfig
    ctx = _ctx()
    book = PaperBook(starting_capital=1_000_000.0)
    gov = RiskGovernor(GovernorConfig.from_settings())
    gov.cfg.seller_mode = False
    naked = next((c for c in generate_candidates(ctx, book.equity()) if not c.defined_risk), None)
    if naked is not None:  # short_strangle exists on the demo chain
        v = gov.evaluate(naked, book, ctx.spot)
        assert "naked_blocked" in v.reasons


def test_kill_switch_flattens_and_halts():
    ctx = _ctx()
    book = PaperBook(starting_capital=1_000_000.0)
    gov = RiskGovernor()
    for cand in _trade_candidates(ctx, book.equity()):
        book.try_open(cand, ctx, gov)
    # Force a drawdown past the kill-switch threshold and trip it.
    book.peak_equity = book.equity() / (1.0 - SETTINGS.paper_max_drawdown_pct) * 1.01
    assert book.maybe_kill_switch(ctx) is True
    assert book.halted is True
    assert not book.open  # flattened


# --- ORM persistence --------------------------------------------------------
def test_paper_orm_persists(tmp_path):
    from anvil.db import create_all, dispose_engine
    from anvil.db import engine as dbengine
    from anvil.db import repo as dbrepo
    from anvil.paper import repo as prepo

    dbengine.init_engine(f"sqlite+aiosqlite:///{(tmp_path / 'paper.db').as_posix()}")

    async def body():
        await create_all()
        sm = dbengine.get_sessionmaker()
        ctx = _ctx()
        book = PaperBook(starting_capital=1_000_000.0)
        gov = RiskGovernor()
        cand = next(c for c in _trade_candidates(ctx, book.equity()))
        pos, _ = book.try_open(cand, ctx, gov)
        assert pos is not None

        async with sm() as s:
            u = await dbrepo.create_user(s, email="owner@example.com", password_hash="h")
            acct = await prepo.ensure_account(s, user_id=u.id, starting_capital=1_000_000.0)
            run = await prepo.create_run(s, user_id=u.id, account_id=acct.id, mode="replay", underlyings=["NIFTY"])
            rec = await prepo.insert_recommendation(s, user_id=u.id, account_id=acct.id, run_id=run.id, cand=cand, ts=ctx.timestamp)
            row = await prepo.insert_position(s, user_id=u.id, account_id=acct.id, run_id=run.id, recommendation_id=rec.id, pos=pos)
            ep = book.record_equity_point(ctx.timestamp)
            await prepo.insert_equity_point(s, user_id=u.id, account_id=acct.id, run_id=run.id, ep=ep)
            await s.commit()
            uid, rid = u.id, run.id
            assert row.id is not None

        async with sm() as s:
            positions = await prepo.list_positions(s, uid)
            assert len(positions) == 1 and positions[0].strategy == cand.strategy
            fills = await prepo.list_fills(s, uid)
            assert len(fills) == len(pos.fills) and fills[0].status == "FILLED_SIMULATED"
            curve = await prepo.list_equity_curve(s, uid, rid)
            assert len(curve) == 1

        await dispose_engine()

    asyncio.run(body())
