"""User-scoped account endpoints (gated by current_user): profile + watchlists.

Market analytics stay public within the instance (same data for everyone); only genuinely
user-scoped surfaces require login. The whole instance is private behind the deploy gate."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import current_user
from ...db import repo
from ...db.engine import get_session
from ...db.models import User

router = APIRouter(prefix="/api", tags=["account"])


class ProfilePatch(BaseModel):
    explain_mode: str | None = None  # simple | trader | expert
    benchmark: str | None = None
    onboarded: bool | None = None
    prefs: dict | None = None


class WatchlistIn(BaseModel):
    name: str
    symbols: list[str] = []
    is_default: bool = False


def _profile_dict(prof) -> dict:
    return {
        "explain_mode": prof.explain_mode,
        "onboarded": prof.onboarded,
        "benchmark": prof.benchmark,
        "prefs": prof.prefs,
        "feature_flags": prof.feature_flags,
    }


@router.get("/profile")
async def get_profile(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return _profile_dict(await repo.ensure_profile(session, user.id))


@router.patch("/profile")
async def patch_profile(
    body: ProfilePatch, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    if body.explain_mode is not None and body.explain_mode not in ("simple", "trader", "expert"):
        raise HTTPException(400, "explain_mode must be simple|trader|expert")
    prof = await repo.update_profile(
        session,
        user.id,
        explain_mode=body.explain_mode,
        benchmark=body.benchmark,
        onboarded=body.onboarded,
        prefs=body.prefs,
    )
    return _profile_dict(prof)


def _wl_dict(wl) -> dict:
    return {"id": wl.id, "name": wl.name, "symbols": wl.symbols, "is_default": wl.is_default}


@router.get("/watchlists")
async def get_watchlists(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [_wl_dict(w) for w in await repo.list_watchlists(session, user.id)]


@router.post("/watchlists")
async def create_watchlist(
    body: WatchlistIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    wl = await repo.add_watchlist(
        session, user_id=user.id, name=body.name, symbols=body.symbols, is_default=body.is_default
    )
    return _wl_dict(wl)


@router.delete("/watchlists/{wl_id}")
async def delete_watchlist(
    wl_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    if not await repo.delete_watchlist(session, user.id, wl_id):
        raise HTTPException(404, "Watchlist not found")
    return {"deleted": wl_id}
