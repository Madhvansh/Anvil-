"""Decision-Brief API — the buyer's environment-gate → strike-action read for one underlying.

Read-only and honest: it COMPUTES the brief (touch-prob, VRP, regime, IV-crush) on current data + the
cached Yahoo OHLC history, and returns it alongside the MEASURED structural reliability curve
(``metrics_for_structural``). It does NOT record forecasts on a GET (that would flood the ledger on a
live timestamp) — recording for calibration accrual is the nightly ``anvil decision-brief --record``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from starlette.concurrency import run_in_threadpool

from ...db.models import User
from ...engine.decision_brief import decision_brief
from ...ingest import yahoo
from ...ingest.base import attach_parity_forward
from ...ledger.ledger import CalibrationLedger
from ...strategy.context import SignalContext
from ..deps import get_source, require_tips

router = APIRouter(prefix="/api/decision-brief", tags=["decision-brief"])


def _compute(underlying: str, horizon_days: int) -> dict:
    conn = get_source()
    chain = attach_parity_forward(conn.get_chain(underlying))
    ctx = SignalContext(chain, source=conn.name)
    history = yahoo.history_for(underlying)  # cache-first; empty when nothing fetched yet
    brief = decision_brief(ctx, history_ohlc=yahoo.ohlc_tuples(history),
                           horizon_days=horizon_days)
    led = CalibrationLedger()
    try:
        structural = led.metrics_for_structural()
    finally:
        led.close()
    out = brief.to_dict()
    out["source"] = conn.name
    out["history_days"] = len(history)
    out["structural_calibration"] = structural
    return out


@router.get("/{underlying}")
async def get_brief(
    underlying: str,
    horizon_days: int = Query(default=5, ge=1, le=30),
    user: User = Depends(require_tips),
):
    """Environment verdict (FAVORABLE/…/ABSTAIN + flip condition) + VRP-adjusted P(touch) per strike,
    plus the measured touch/VRP reliability. Analytics, not edge-proven."""
    return await run_in_threadpool(_compute, underlying, horizon_days)
