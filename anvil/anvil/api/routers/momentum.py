"""Momentum API — multi-timeframe + options-flow momentum for an underlying (stock OR index).

PUBLIC analytics surface (no sized/actionable output): the consensus ``MomentumRead``, options-flow
velocity (``FlowMomentumRead``), the fired momentum factors, and the honestly-gated prediction. Built on
the shared prediction spine via ``tips.momentum.momentum_for_chain`` so it can never drift from how tips
are computed. Behind login + the TIPS_ENABLED flag (``require_tips``); CPU/DuckDB work runs in a
threadpool like the other read handlers.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from starlette.concurrency import run_in_threadpool

from ...config import SETTINGS
from ...db.models import User
from ...engine.util import json_safe
from ...ingest.base import attach_parity_forward
from ...store.bars import BarStore
from ...store.timeseries import SnapshotStore
from ...tips.eod import tip_source_for
from ...tips.momentum import momentum_for_chain
from ...tips.store import TipValidationStore
from ..deps import TIP_DISCLAIMER, get_source, require_tips

router = APIRouter(prefix="/api/momentum", tags=["momentum"])


def _open(factory):
    """Open a DuckDB-backed store, degrading to None if it can't be opened (cross-process lock).
    ``momentum_for_chain``/``build_series_block`` already treat a None store as "no series" and the
    prediction stays always-present, so a locked store just trims overlays — never a 500."""
    try:
        return factory()
    except Exception:  # noqa: BLE001 - overlay store is best-effort
        return None


def _compute_momentum(underlying: str, equity: float) -> dict:
    conn = get_source()
    chain = attach_parity_forward(conn.get_chain(underlying))
    src = tip_source_for(conn.name)
    bars = _open(BarStore)
    snaps = _open(SnapshotStore)
    vstore = _open(TipValidationStore)
    try:
        payload = momentum_for_chain(
            chain, source=src, equity=equity, bar_store=bars, snap_store=snaps, validation_store=vstore)
    finally:
        for _s in (bars, snaps, vstore):
            if _s is not None:
                _s.close()
    payload["source"] = src
    payload["disclaimer"] = TIP_DISCLAIMER
    return json_safe(payload)


@router.get("/{underlying}")
async def momentum_for(underlying: str, user: User = Depends(require_tips)):
    """Multi-timeframe + options-flow momentum read for ``underlying`` (PUBLIC analytics: momentum
    consensus, flow velocity, fired factors, gated prediction — no sized/actionable output)."""
    return await run_in_threadpool(
        _compute_momentum, underlying, float(SETTINGS.paper_starting_capital))
