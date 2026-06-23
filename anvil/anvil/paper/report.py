"""Run report — the effectiveness scorecard for a paper session.

P&L (gross + net of charges), win rate, profit factor, expectancy, Sharpe/Sortino, max drawdown,
best/worst trade, exposure, and per-strategy / per-underlying / per-regime attribution, plus the
Performance Lab per-trade detail and (optionally) the owner-only paper conviction calibration.
Pure over the in-memory book; mirrors the json-safe shape of the montecarlo output.
"""

from __future__ import annotations

import numpy as np

from ..engine.util import json_safe
from .perf_lab import performance_lab


def _equity_series(book) -> np.ndarray:
    return np.array([ep.equity for ep in book.equity_points], dtype=float)


def _sharpe_sortino(eq: np.ndarray) -> tuple[float | None, float | None, float | None]:
    if eq.size < 3:
        return None, None, None
    rets = np.diff(eq) / np.where(eq[:-1] == 0, 1.0, eq[:-1])
    if rets.size == 0 or rets.std(ddof=1) == 0:
        vol = float(rets.std(ddof=1)) if rets.size else None
        return None, None, vol
    ann = np.sqrt(252.0)
    sharpe = float(rets.mean() / rets.std(ddof=1) * ann)
    downside = rets[rets < 0]
    sortino = float(rets.mean() / downside.std(ddof=1) * ann) if downside.size > 1 and downside.std(ddof=1) > 0 else None
    return round(sharpe, 3), (round(sortino, 3) if sortino is not None else None), round(float(rets.std(ddof=1)), 6)


def _max_drawdown(eq: np.ndarray) -> float:
    if eq.size == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    dd = (peak - eq) / np.where(peak == 0, 1.0, peak)
    return round(float(dd.max()), 4)


def _attribution(closed, key) -> dict:
    out: dict[str, dict] = {}
    for p in closed:
        k = str(key(p))
        b = out.setdefault(k, {"n": 0, "net_pnl": 0.0, "wins": 0})
        b["n"] += 1
        b["net_pnl"] += p.realized_pnl
        b["wins"] += 1 if p.realized_pnl > 0 else 0
    for b in out.values():
        b["net_pnl"] = round(b["net_pnl"], 2)
        b["win_rate"] = round(b["wins"] / b["n"], 4) if b["n"] else 0.0
    return out


def run_report(book, *, ledger=None, missed: list[dict] | None = None, meta: dict | None = None) -> dict:
    closed = book.closed
    eq = _equity_series(book)
    nets = np.array([p.realized_pnl for p in closed], dtype=float)
    wins = nets[nets > 0]
    losses = nets[nets < 0]
    gross_profit = float(wins.sum()) if wins.size else 0.0
    gross_loss = float(-losses.sum()) if losses.size else 0.0
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else (None if gross_profit == 0 else float("inf"))
    sharpe, sortino, vol = _sharpe_sortino(eq)
    ending_equity = float(eq[-1]) if eq.size else book.equity()

    report = {
        "meta": meta or {},
        "summary": {
            "starting_capital": round(book.starting_capital, 2),
            "ending_equity": round(ending_equity, 2),
            "net_pnl": round(ending_equity - book.starting_capital, 2),
            "return_pct": round((ending_equity / book.starting_capital - 1.0) * 100.0, 3) if book.starting_capital else None,
            "realized_pnl": round(book.realized_pnl, 2),
            "open_positions": len(book.open),
            "halted": book.halted,
        },
        "trades": {
            "n_total": len(closed),
            "n_wins": int(wins.size),
            "n_losses": int(losses.size),
            "win_rate": round(float((nets > 0).mean()), 4) if nets.size else None,
            "profit_factor": profit_factor,
            "expectancy": round(float(nets.mean()), 2) if nets.size else None,
            "avg_win": round(float(wins.mean()), 2) if wins.size else None,
            "avg_loss": round(float(losses.mean()), 2) if losses.size else None,
            "best": round(float(nets.max()), 2) if nets.size else None,
            "worst": round(float(nets.min()), 2) if nets.size else None,
        },
        "risk": {
            "max_drawdown": _max_drawdown(eq),
            "sharpe_annualized": sharpe,
            "sortino_annualized": sortino,
            "per_tick_vol": vol,
            "avg_gross_exposure": round(float(np.mean([ep.gross_exposure for ep in book.equity_points])), 2) if book.equity_points else 0.0,
            "max_gross_exposure": round(float(np.max([ep.gross_exposure for ep in book.equity_points])), 2) if book.equity_points else 0.0,
            "note": "Sharpe/Sortino annualized with sqrt(252) over equity-point returns; a research estimate, not a verified track record.",
        },
        "attribution": {
            "by_strategy": _attribution(closed, lambda p: p.strategy),
            "by_underlying": _attribution(closed, lambda p: p.underlying),
            "by_regime": _attribution(closed, lambda p: p.opened_regime),
        },
        "performance_lab": performance_lab(closed),
        "equity_curve": [ep.as_dict() for ep in book.equity_points],
        "missed_opportunities": missed or [],
        "caveat": "Paper simulation. Fills are modeled (spread/slippage) and margin is SPAN-lite — a research estimate, not investment advice.",
    }
    if ledger is not None:
        from .calibration import paper_calibration

        report["conviction_calibration"] = paper_calibration(ledger)
    return json_safe(report)
