"""Grounded, deterministic narration of the current regime (every number from the engine)."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import DISCLAIMER, cached_analyze

router = APIRouter(prefix="/api", tags=["agent"])


@router.get("/agent/narrate/{underlying}")
def agent_narrate(underlying: str, expiry: str | None = None):
    from ...agent.analyst import GroundedAnalyst

    payload, _ = cached_analyze(underlying, expiry)
    return {"answer": GroundedAnalyst().narrate(payload), "grounded": True, "disclaimer": DISCLAIMER}
