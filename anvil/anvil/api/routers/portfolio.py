"""Beta-weighted portfolio risk (gated — it surfaces the user's positions)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ...auth.deps import current_user
from ...db.models import User
from ...pipeline import analyze_chain
from ..deps import get_source

router = APIRouter(prefix="/api", tags=["portfolio"])


@router.get("/portfolio-risk")
def portfolio_risk(benchmark_price: float = 24000.0, user: User = Depends(current_user)):
    # Position data is user-scoped → requires login. Fetched fresh (not the public cache).
    conn = get_source()
    if not conn.provides_positions:
        raise HTTPException(400, f"Source {conn.name} has no positions. Use kite/groww/demo.")
    ch = conn.get_chain("NIFTY")
    payload = analyze_chain(ch, conn.get_positions(), source=conn.name)
    return payload.get("portfolio", {})
