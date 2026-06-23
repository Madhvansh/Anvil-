"""Phase 5 — the live trust dial: one composed honesty panel.

Reliability curve + accuracy-at-coverage operating point + coverage % + the v2 tail-stats scorecard
(over RESOLVED live tips) + the per-cell certified verdicts + the VRP-prior anchor (labeled "prior,
not a track record") + the gate/armed status. Everything is read-only and DISPLAY-only — none of it
feeds the gate or sizing. The scorecard ports ``tracker_v2._metrics``: win-rate is NEVER shown alone.
"""

from __future__ import annotations

import numpy as np

from ..config import SETTINGS
from .types import TIP_DISCLAIMER


def _tail_metrics(pnls: list[float]) -> dict:
    """Mandatory tail block (₹) over per-trade net P&L — maxDD/worst/CVaR5%/Sharpe/Sortino/Calmar."""
    if not pnls:
        return {"n": 0}
    a = np.asarray(pnls, dtype=float)
    n = int(a.size)
    wins, losses = a[a > 0], a[a <= 0]
    eq = np.cumsum(a)
    dd = eq - np.maximum.accumulate(eq)
    k = max(1, int(np.ceil(0.05 * n)))
    cvar = float(np.sort(a)[:k].mean())
    sd = float(a.std(ddof=1)) if n > 1 else 0.0
    downside = a[a < 0]
    dsd = float(np.sqrt((downside ** 2).mean())) if downside.size else 0.0
    ann = float(np.sqrt(252.0))
    total = float(a.sum())
    gross_loss = float(-losses.sum())
    return {
        "n": n,
        "win_rate": round(float((a > 0).mean()), 4),
        "expectancy_inr": round(float(a.mean()), 2),
        "total_pnl_inr": round(total, 2),
        "profit_factor": round(float(wins.sum()) / gross_loss, 3) if gross_loss > 0 else None,
        "sharpe": round(float(a.mean() / sd * ann), 3) if sd > 0 else None,
        "sortino": round(float(a.mean() / dsd * ann), 3) if dsd > 0 else None,
        # --- TAIL (mandatory, never hidden) ---
        "max_drawdown_inr": round(float(dd.min()), 2),
        "worst_trade_inr": round(float(a.min()), 2),
        "cvar_5pct_inr": round(cvar, 2),
        "calmar": round(total / abs(float(dd.min())), 3) if dd.min() < 0 else None,
    }


def resolved_scorecard(istore, sources: tuple[str, ...] = ("tip_live",)) -> dict:
    """The honest scorecard over RESOLVED live tips — tail stats + open-excluded-but-counted."""
    samples = istore.resolved_samples(sources)
    block = _tail_metrics([float(s["net"]) for s in samples])
    block["resolved"] = block.get("n", 0)
    return block


def _operating_point(cells: list[dict] | None, gate0_artifact: dict | None) -> dict:
    """Accuracy-at-coverage operating point: the persisted gate0 report when present, else a summary
    of the best headline-eligible live cell (or 'no certified cell yet')."""
    if gate0_artifact:
        return gate0_artifact.get("operating_point") or gate0_artifact
    headline = [c for c in (cells or []) if c.get("headline_eligible")]
    if not headline:
        return {"status": "no certified cell yet — abstaining (the honest default)"}
    best = max(headline, key=lambda c: float(c.get("t_stat") or 0.0))
    return {"status": "live", "n": best.get("n"), "win_rate": best.get("win_rate"),
            "t_stat": best.get("t_stat"), "dsr": best.get("dsr"),
            "structure": best.get("structure"), "underlying": best.get("underlying")}


def build_trust_dial(*, led, istore, vstore, gate0_artifact: dict | None = None,
                     vrp_prior: dict | None = None, coverage_underlying: str | None = None) -> dict:
    """Compose the live trust dial. Read-only; calibration/coverage shown ALONGSIDE, never feeding
    the gate or sizing. The gate/armed status reads the SAME vstore the gate writes."""
    from ..gating import gate0_passed, personal_mode_armed

    cells = vstore.all()
    return {
        "reliability": led.metrics_for_tips(),
        "accuracy_at_coverage": _operating_point(cells, gate0_artifact),
        "coverage": istore.coverage_rolling(n_days=20, underlying=coverage_underlying),
        "scorecard": resolved_scorecard(istore),
        "cells": cells,
        "vrp_prior": ({**vrp_prior, "note": "prior, NOT a track record"} if vrp_prior else None),
        "gate": {
            "armed": personal_mode_armed(vstore),
            "gate0_passed": gate0_passed(vstore),
            "personal_mode": bool(SETTINGS.personal_mode),
        },
        "disclaimer": TIP_DISCLAIMER,
    }
