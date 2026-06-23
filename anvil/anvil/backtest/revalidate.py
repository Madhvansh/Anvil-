"""Re-validate the gate from accumulated LIVE evidence.

The historical bhavcopy backtest seeds the ``tip_validation`` cells once; this job keeps them honest
as forward ``tip_live`` outcomes accrue. It reads the resolved issued tips (with their realized
``ret``/``net_pnl``), re-aggregates them into the same per-cell shape, and re-runs the full battery —
so a cell can EARN ``headline_eligible`` once enough real tips land at/above their stated conviction,
or LOSE it if live evidence diverges. Scheduled weekly (or after each EOD cycle).

Live and backtest evidence stay separate by source class (a cell is keyed on structure/regime/
underlying, not on which run produced it), so this never blends synthetic into the live verdict.
"""

from __future__ import annotations

from ..tips.store import IssuedTipStore, TipValidationStore
from .aggregate import validate_cells
from .horizon import embargo_from_pairs


def revalidate_from_live(
    *, issued_store: IssuedTipStore | None = None, validation_store: TipValidationStore | None = None,
    sources: tuple[str, ...] = ("tip_live",), min_samples: int = 50, updated_ts: str = "",
) -> dict:
    """Re-derive per-cell verdicts from resolved live tips and upsert them. Returns a summary."""
    owns_is, owns_vs = issued_store is None, validation_store is None
    istore = issued_store or IssuedTipStore()
    vstore = validation_store or TipValidationStore()
    try:
        cells = istore.resolved_cells(sources=sources)
        res_days = sorted({d for c in cells.values() for d in c["by_day"]})
        # Embargo = the longest live label horizon (issue→resolution, trading days), so multi-day live
        # tips can't leak train↔test in the OOF edge check (was: silent embargo=5 regardless of tenor).
        embargo = embargo_from_pairs(istore.resolved_spans(sources=sources))
        reports, gpbo = validate_cells(
            cells, res_days, min_samples=min_samples, updated_ts=updated_ts, embargo=embargo)
        for rep in reports:
            vstore.upsert(rep)
        return {
            "cells": len(cells),
            "headline_cells": sum(1 for r in reports if r.headline_eligible),
            "global_pbo": gpbo,
            "resolved_total": sum(len(c["returns"]) for c in cells.values()),
        }
    finally:
        if owns_is:
            istore.close()
        if owns_vs:
            vstore.close()
