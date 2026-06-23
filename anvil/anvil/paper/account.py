"""PaperBook — the in-memory paper-trading account + position lifecycle.

open_candidate -> mark_to_market -> manage (exit rules) -> close, with an equity curve and a
hard drawdown kill-switch. Cash accounting is exact and reconciles realized + unrealized P&L
against equity. Pricing for unrealized MTM comes from ``mtm`` (the engine's Black-76 path); close
fills come from the ``PaperBrokerGateway`` (spread + slippage + India F&O charges).
"""

from __future__ import annotations

import copy

from ..config import SETTINGS
from ..engine.util import year_fraction
from ..strategy.context import SignalContext
from ..strategy.types import LONG_VOL, NEUTRAL, SHORT_VOL, TradeCandidate
from . import margin, mtm
from .gateway import PaperBrokerGateway
from .state import EquityPoint, Fill, PaperLeg, PaperPosition

# Reject reasons the book may resolve by reducing trade size (vs. hard vetoes like conviction).
_DOWNSIZE_REASONS = {"exposure_cap", "insufficient_margin", "underlying_lot_cap"}


def rescale_units(cand: TradeCandidate, k: int) -> TradeCandidate:
    """Return a copy of an already-sized candidate scaled to ``k`` units (k < current units)."""
    u = max(1, cand.units)
    factor = k / u
    nc = copy.deepcopy(cand)
    nc.units = k
    nc.max_loss = round(cand.max_loss * factor, 2)
    nc.max_profit = round(cand.max_profit * factor, 2) if cand.max_profit is not None else None
    nc.entry_debit_credit = round(cand.entry_debit_credit * factor, 2)
    nc.expected_value = round(cand.expected_value * factor, 2)
    for leg in nc.legs:
        leg.lots = k
    return nc

_OPP_REGIME_FOR_PREMIUM = "negative_gamma_trend_amplify"
_OPP_REGIME_FOR_LONGVOL = "positive_gamma_mean_revert"


class PaperBook:
    def __init__(
        self,
        starting_capital: float | None = None,
        gateway: PaperBrokerGateway | None = None,
        name: str = "paper",
    ):
        self.name = name
        self.starting_capital = float(starting_capital if starting_capital is not None else SETTINGS.paper_starting_capital)
        self.cash = self.starting_capital
        self.realized_pnl = 0.0
        self.peak_equity = self.starting_capital
        self.day_start_equity = self.starting_capital
        self.gateway = gateway or PaperBrokerGateway()
        self.open: list[PaperPosition] = []
        self.closed: list[PaperPosition] = []
        self.equity_points: list[EquityPoint] = []
        self.halted = False
        self._next_id = 1

    # --- valuation ----------------------------------------------------------
    def equity(self) -> float:
        return float(self.cash + sum(p.mark_value for p in self.open))

    def gross_exposure(self) -> float:
        return float(sum(p.reserved_margin for p in self.open))

    def buying_power(self) -> float:
        return float(self.equity() - self.gross_exposure())

    def unrealized_total(self) -> float:
        return float(sum(p.unrealized_pnl for p in self.open))

    def drawdown(self) -> float:
        peak = max(self.peak_equity, 1e-9)
        return float(max(0.0, 1.0 - self.equity() / peak))

    # --- open ---------------------------------------------------------------
    def _leg_quote(self, ctx: SignalContext, leg) -> tuple[float, float | None, float | None]:
        """Return (mid, bid, ask) for a candidate leg from the live chain."""
        if leg.option_type is not None and leg.strike is not None:
            row = ctx.row(leg.strike, leg.option_type)
            mid = ctx.mid(leg.strike, leg.option_type) or leg.ref_price
            return float(mid), (row.bid if row else None), (row.ask if row else None)
        return float(leg.ref_price), None, None  # FUT/EQ: mark at ref (forward/spot)

    def open_candidate(self, cand: TradeCandidate, ctx: SignalContext, ts: str | None = None) -> PaperPosition:
        ts = ts or ctx.timestamp
        lot = cand.lot_size
        fills: list[Fill] = []
        legs: list[PaperLeg] = []
        entry_value = 0.0
        open_charges = 0.0
        for leg in cand.legs:
            mid, bid, ask = self._leg_quote(ctx, leg)
            qty = int(leg.lots) * lot
            fill = self.gateway.simulate_fill(
                side=leg.side, qty=qty, lots=leg.lots, mid=mid, bid=bid, ask=ask,
                instrument_type=leg.instrument_type, underlying=cand.underlying,
                symbol=leg.symbol or cand.underlying, ts=ts, kind="open",
                strike=leg.strike, expiry=leg.expiry,
                option_type=(leg.option_type.value if leg.option_type else None),
            )
            fills.append(fill)
            entry_value += leg.sign * fill.fill_price * qty
            open_charges += fill.charges["total"]
            legs.append(PaperLeg(
                side=leg.side, lots=leg.lots, instrument_type=leg.instrument_type, expiry=leg.expiry,
                entry_price=fill.fill_price, option_type=leg.option_type, strike=leg.strike, symbol=leg.symbol,
            ))

        self.cash -= entry_value + open_charges
        reserved = margin.required_margin(cand, spot=ctx.spot)
        target_pnl, stop_pnl = self._exit_thresholds(cand, entry_value)
        exit_rules = dict(cand.exit_rules)
        exit_rules.update({"target_pnl": round(target_pnl, 2), "stop_pnl": round(stop_pnl, 2)})

        pos = PaperPosition(
            id=self._next_id, underlying=cand.underlying, strategy=cand.strategy, direction=cand.direction,
            opened_at=ts, lot_size=lot, legs=legs, entry_value=round(entry_value, 2),
            max_loss=cand.max_loss, max_profit=cand.max_profit, reserved_margin=round(reserved, 2),
            conviction=cand.conviction, edge_prob=cand.edge_prob, opened_regime=ctx.regime.label,
            exit_rules=exit_rules, charges_paid=round(open_charges, 2),
            recommendation=cand.to_dict(), fills=fills,
        )
        self._next_id += 1
        self._mark_one(pos, ctx)
        self.open.append(pos)
        return pos

    def try_open(self, cand: TradeCandidate, ctx: SignalContext, governor, ts: str | None = None):
        """Governor-gated open. If the only blockers are margin/exposure, reduce units to fit.

        Returns (PaperPosition | None, verdict). Hard vetoes (conviction, liquidity, halt, naked
        without seller-mode) are never downsized around.
        """
        verdict = governor.evaluate(cand, self, ctx.spot)
        if verdict.approved:
            return self.open_candidate(cand, ctx, ts=ts), verdict
        if cand.units > 1 and set(verdict.reasons) <= _DOWNSIZE_REASONS:
            for k in range(cand.units - 1, 0, -1):
                trial = rescale_units(cand, k)
                vk = governor.evaluate(trial, self, ctx.spot)
                if vk.approved:
                    return self.open_candidate(trial, ctx, ts=ts), vk
        return None, verdict

    def _exit_thresholds(self, cand: TradeCandidate, entry_value: float) -> tuple[float, float]:
        er = cand.exit_rules
        tp_pct = er.get("take_profit_pct", 0.5)
        sl_pct = er.get("stop_loss_pct", 1.0)
        if entry_value < 0:  # credit structure
            credit = cand.max_profit or abs(entry_value)
            target = tp_pct * credit
            stop = -min(cand.max_loss, sl_pct * credit)
        else:  # debit structure
            base = cand.max_loss
            target = tp_pct * (cand.max_profit if cand.max_profit else base)
            stop = -sl_pct * base
        return target, stop

    # --- mark + manage ------------------------------------------------------
    def _mark_one(self, pos: PaperPosition, ctx: SignalContext) -> None:
        pos.mark_value = round(mtm.mark_value(pos, ctx.chain), 2)
        pos.unrealized_pnl = round(pos.mark_value - pos.entry_value - pos.charges_paid, 2)
        pos.mae = round(min(pos.mae, pos.unrealized_pnl), 2)  # max adverse excursion
        pos.mfe = round(max(pos.mfe, pos.unrealized_pnl), 2)  # max favorable excursion
        pos.greeks = mtm.net_greeks(pos, ctx.chain)

    def mark_to_market(self, ctx: SignalContext) -> None:
        for pos in self.open:
            if pos.underlying == ctx.underlying:
                self._mark_one(pos, ctx)
        self.peak_equity = max(self.peak_equity, self.equity())

    def _exit_reason(self, pos: PaperPosition, ctx: SignalContext) -> str | None:
        er = pos.exit_rules
        u = pos.unrealized_pnl
        if "target_pnl" in er and u >= er["target_pnl"] and er["target_pnl"] > 0:
            return "take_profit"
        if "stop_pnl" in er and u <= er["stop_pnl"]:
            return "stop_loss"
        days_left = year_fraction(pos.legs[0].expiry, ctx.timestamp) * 365.0
        if days_left <= 0.5:
            return "time_exit"
        if er.get("regime_flip_exit"):
            if pos.direction in (NEUTRAL, SHORT_VOL) and ctx.regime.label == _OPP_REGIME_FOR_PREMIUM:
                return "regime_flip"
            if pos.direction == LONG_VOL and ctx.regime.label == _OPP_REGIME_FOR_LONGVOL:
                return "regime_flip"
        return None

    def manage(self, ctx: SignalContext) -> list[PaperPosition]:
        closed_now: list[PaperPosition] = []
        for pos in list(self.open):
            if pos.underlying != ctx.underlying:
                continue
            reason = self._exit_reason(pos, ctx)
            if reason:
                self.close_position(pos, ctx, reason)
                closed_now.append(pos)
        return closed_now

    # --- close --------------------------------------------------------------
    def close_position(self, pos: PaperPosition, ctx: SignalContext, reason: str, ts: str | None = None) -> PaperPosition:
        ts = ts or ctx.timestamp
        close_value = 0.0
        close_charges = 0.0
        for leg in pos.legs:
            qty = leg.qty(pos.lot_size)
            rev_side = "SELL" if leg.side.upper() == "BUY" else "BUY"
            if leg.option_type is not None and leg.strike is not None:
                row = ctx.row(leg.strike, leg.option_type)
                mid = ctx.mid(leg.strike, leg.option_type) or leg.entry_price
                bid, ask = (row.bid if row else None), (row.ask if row else None)
            else:
                mid, bid, ask = float(ctx.chain.future_price or ctx.spot), None, None
            fill = self.gateway.simulate_fill(
                side=rev_side, qty=qty, lots=leg.lots, mid=mid, bid=bid, ask=ask,
                instrument_type=leg.instrument_type, underlying=pos.underlying,
                symbol=leg.symbol or pos.underlying, ts=ts, kind="close",
                strike=leg.strike, expiry=leg.expiry,
                option_type=(leg.option_type.value if leg.option_type else None),
            )
            pos.fills.append(fill)
            close_value += leg.sign * fill.fill_price * qty
            close_charges += fill.charges["total"]

        realized = (close_value - pos.entry_value) - (pos.charges_paid + close_charges)
        self.cash += close_value - close_charges
        self.realized_pnl += realized
        pos.realized_pnl = round(realized, 2)
        pos.charges_paid = round(pos.charges_paid + close_charges, 2)
        pos.status = "closed"
        pos.closed_at = ts
        pos.close_reason = reason
        pos.mark_value = 0.0
        pos.unrealized_pnl = 0.0
        if pos in self.open:
            self.open.remove(pos)
        self.closed.append(pos)
        return pos

    def flatten(self, ctx: SignalContext, reason: str = "flatten") -> list[PaperPosition]:
        return [self.close_position(p, ctx, reason) for p in list(self.open) if p.underlying == ctx.underlying]

    def maybe_kill_switch(self, ctx: SignalContext) -> bool:
        """Trip the drawdown kill-switch: flatten + halt new entries. Returns True if tripped."""
        if self.halted:
            return True
        if self.drawdown() >= SETTINGS.paper_max_drawdown_pct:
            self.flatten(ctx, reason="kill_switch")
            self.halted = True
            return True
        return False

    # --- equity curve -------------------------------------------------------
    def record_equity_point(self, ts: str) -> EquityPoint:
        eq = self.equity()
        self.peak_equity = max(self.peak_equity, eq)
        ep = EquityPoint(
            ts=ts,
            equity=round(eq, 2),
            cash=round(self.cash, 2),
            unrealized_pnl=round(self.unrealized_total(), 2),
            realized_pnl=round(self.realized_pnl, 2),
            gross_exposure=round(self.gross_exposure(), 2),
            net_delta=round(sum(p.greeks.get("net_delta", 0.0) for p in self.open), 2),
            open_positions=len(self.open),
            drawdown=round(self.drawdown(), 4),
        )
        self.equity_points.append(ep)
        return ep
