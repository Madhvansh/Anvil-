"""Performance Lab — per-trade scoring (the monetization proof).

For every closed paper trade: gross P&L, net P&L after charges, MAE / MFE, slippage cost, signal
confidence (conviction) vs realized outcome, and the close reason. Plus aggregates that show
whether higher-conviction trades actually win more (the calibration the ledger formalizes).
Pure over the in-memory closed positions — no I/O.
"""

from __future__ import annotations

import numpy as np

from .state import PaperPosition


def _slippage_cost(pos: PaperPosition) -> float:
    return float(sum(abs(f.slippage) * f.qty for f in pos.fills))


def trade_row(pos: PaperPosition) -> dict:
    net = pos.realized_pnl
    gross = round(net + pos.charges_paid, 2)
    return {
        "position_id": pos.id,
        "underlying": pos.underlying,
        "strategy": pos.strategy,
        "direction": pos.direction,
        "opened_at": pos.opened_at,
        "closed_at": pos.closed_at,
        "close_reason": pos.close_reason,
        "units": int(pos.recommendation.get("units", 1)),
        "conviction": round(pos.conviction, 4),
        "edge_prob": round(pos.edge_prob, 4),
        "gross_pnl": gross,
        "net_pnl": round(net, 2),
        "charges": round(pos.charges_paid, 2),
        "slippage_cost": round(_slippage_cost(pos), 2),
        "mae": round(pos.mae, 2),
        "mfe": round(pos.mfe, 2),
        "max_loss": pos.max_loss,
        "won": bool(net > 0),
        "opened_regime": pos.opened_regime,
    }


def _confidence_buckets(rows: list[dict]) -> list[dict]:
    """Did higher-conviction trades win more? Bucket by conviction and show realized win-rate."""
    edges = [(0.0, 0.5), (0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.01)]
    out = []
    for lo, hi in edges:
        sub = [r for r in rows if lo <= r["conviction"] < hi]
        if not sub:
            continue
        out.append({
            "bucket": f"{lo:.2f}-{hi:.2f}",
            "n": len(sub),
            "mean_conviction": round(float(np.mean([r["conviction"] for r in sub])), 4),
            "win_rate": round(float(np.mean([r["won"] for r in sub])), 4),
            "net_pnl": round(float(np.sum([r["net_pnl"] for r in sub])), 2),
        })
    return out


def performance_lab(closed: list[PaperPosition]) -> dict:
    rows = [trade_row(p) for p in closed]
    if not rows:
        return {"trades": [], "n": 0, "aggregates": {}, "confidence_buckets": []}
    nets = np.array([r["net_pnl"] for r in rows], dtype=float)
    return {
        "n": len(rows),
        "trades": rows,
        "aggregates": {
            "avg_mae": round(float(np.mean([r["mae"] for r in rows])), 2),
            "avg_mfe": round(float(np.mean([r["mfe"] for r in rows])), 2),
            "total_slippage_cost": round(float(np.sum([r["slippage_cost"] for r in rows])), 2),
            "total_charges": round(float(np.sum([r["charges"] for r in rows])), 2),
            "avg_net_pnl": round(float(nets.mean()), 2),
            "mean_conviction": round(float(np.mean([r["conviction"] for r in rows])), 4),
            "realized_win_rate": round(float(np.mean([r["won"] for r in rows])), 4),
        },
        "confidence_buckets": _confidence_buckets(rows),
    }
