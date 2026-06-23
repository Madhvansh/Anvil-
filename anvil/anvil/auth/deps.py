"""FastAPI auth dependencies. ``current_user`` 401s when no valid session cookie is
present; ``current_user_optional`` returns None instead (for endpoints that personalize
when logged in but still work anonymously). ``require_personal_owner`` is the Phase-4 hard
wall: actionable/sized output is owner-only behind ``ANVIL_PERSONAL_MODE`` (ADR 0006)."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import SETTINGS
from ..db.engine import get_session
from ..db.models import User
from .sessions import COOKIE_NAME, resolve_session


async def current_user_optional(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    return await resolve_session(session, request.cookies.get(COOKIE_NAME))


async def current_user(user: User | None = Depends(current_user_optional)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


async def require_personal_owner(user: User = Depends(current_user)) -> User:
    """Owner-only gate for actionable/sized output (the Phase-4 hard wall, ADR 0006).

    403 unless ``ANVIL_PERSONAL_MODE`` is on AND the caller is the single owner. This is the ONLY
    authority check for the actionable surface; routers depend on it rather than re-implementing it.
    The actionable PAYLOAD is additionally gated on a passing Gate-0 via ``gating.personal_mode_armed``
    so even the owner gets analytics-only until the edge is certified."""
    if not SETTINGS.personal_mode:
        raise HTTPException(status_code=403, detail="Personal mode is disabled (ANVIL_PERSONAL_MODE=false).")
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Owner-only surface.")
    return user
