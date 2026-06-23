"""Risk Governor — the final pre-execution gate, on LIVE account state.

The strategy layer's decision policy filters per-candidate; the governor is the portfolio-level
backstop that the strategy can't see: drawdown kill-switch, daily-loss limit, open-position and
per-underlying caps, gross-exposure and buying-power limits, liquidity/spread floors, and the
naked-short (seller-mode) gate. Every reject carries an explicit reason. Runs before any paper OR
(future) real order — the single most important risk checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import SETTINGS
from ..strategy.types import NO_TRADE, TRADE, TradeCandidate
from . import margin


@dataclass
class GovernorConfig:
    seller_mode: bool
    max_drawdown_pct: float
    max_daily_loss_pct: float
    max_open_positions: int
    max_lots_per_underlying: int
    max_exposure_pct: float
    min_liquidity_oi: float
    max_spread_pct: float

    @classmethod
    def from_settings(cls, s=SETTINGS) -> "GovernorConfig":
        return cls(
            seller_mode=s.paper_seller_mode,
            max_drawdown_pct=s.paper_max_drawdown_pct,
            max_daily_loss_pct=s.paper_max_daily_loss_pct,
            max_open_positions=s.paper_max_open_positions,
            max_lots_per_underlying=s.paper_max_lots_per_underlying,
            max_exposure_pct=s.paper_max_exposure_pct,
            min_liquidity_oi=s.paper_min_liquidity_oi,
            max_spread_pct=s.paper_max_spread_pct,
        )


@dataclass
class Verdict:
    approved: bool
    reasons: list[str]
    required_margin: float

    def as_dict(self) -> dict:
        return {"approved": self.approved, "reasons": self.reasons, "required_margin": round(self.required_margin, 2)}


class RiskGovernor:
    def __init__(self, cfg: GovernorConfig | None = None):
        self.cfg = cfg or GovernorConfig.from_settings()

    def evaluate(self, cand: TradeCandidate, book, spot: float) -> Verdict:
        c = self.cfg
        reasons: list[str] = []
        req = margin.required_margin(cand, spot=spot)
        equity = book.equity()

        if getattr(book, "halted", False):
            reasons.append("halted")
        if cand.action != TRADE:
            reasons.append("not_trade")
        if cand.units < 1:
            reasons.append("unsizable")
        if not cand.defined_risk and not c.seller_mode:
            reasons.append("naked_blocked")
        if book.drawdown() >= c.max_drawdown_pct:
            reasons.append("drawdown_kill")
        if book.realized_pnl <= -c.max_daily_loss_pct * book.day_start_equity:
            reasons.append("daily_loss_limit")
        if len(book.open) >= c.max_open_positions:
            reasons.append("max_positions")

        existing_units = sum(p.recommendation.get("units", 1) for p in book.open if p.underlying == cand.underlying)
        if existing_units + cand.units > c.max_lots_per_underlying:
            reasons.append("underlying_lot_cap")
        if book.gross_exposure() + req > c.max_exposure_pct * equity:
            reasons.append("exposure_cap")
        if req > book.buying_power():
            reasons.append("insufficient_margin")

        min_oi = cand.drivers.get("min_oi")
        if min_oi is not None and 0 < min_oi < c.min_liquidity_oi:
            reasons.append("illiquid")
        ws = cand.drivers.get("worst_spread_pct")
        if ws is not None and ws > c.max_spread_pct:
            reasons.append("wide_spread")

        return Verdict(approved=not reasons, reasons=reasons, required_margin=req)


def cap_short_vol_exposure(candidates: list[TradeCandidate], equity: float, *,
                           max_exposure_pct: float | None = None) -> list[TradeCandidate]:
    """Phase-5 PORTFOLIO short-vol stress cap (ported from v2 ``apply_portfolio_cap``, adversary #11).

    Short-vol legs across NIFTY/BANKNIFTY/SENSEX gap TOGETHER, so a per-candidate cap understates the
    correlated tail. Cap the TOTAL short-vol (``regime_kind == 'short_vol'``) modeled max-loss at
    ``max_exposure_pct`` of equity; keep the highest-ranked, downsize the marginal one to fit, and
    drop (→ NO_TRADE) the rest. Mutates ``units``/``max_loss`` on the affected candidates and returns
    the list (the others are untouched). Additive — call it AFTER per-candidate sizing/gating."""
    pct = SETTINGS.paper_max_exposure_pct if max_exposure_pct is None else max_exposure_pct
    cap = pct * float(equity)
    sv = sorted(
        [c for c in candidates if getattr(c, "regime_kind", "") == "short_vol"
         and c.action == TRADE and int(getattr(c, "units", 0)) > 0],
        key=lambda c: c.rank_score, reverse=True)
    running = 0.0
    for c in sv:
        ml = abs(float(c.max_loss or 0.0))  # already sized (units applied)
        if running + ml <= cap:
            running += ml
            continue
        per_unit = ml / c.units if c.units else 0.0
        fit = int((cap - running) // per_unit) if per_unit > 0 else 0
        reasons = c.score_components.setdefault("no_trade_reasons", [])
        if fit <= 0:
            c.action, c.units, c.max_loss = NO_TRADE, 0, 0.0
            reasons.append("portfolio_short_vol_cap")
        else:
            c.units = fit
            c.max_loss = round(per_unit * fit, 2)
            reasons.append("downsized_by_portfolio_cap")
            running += c.max_loss
    return candidates
