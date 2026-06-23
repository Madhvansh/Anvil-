"""Authentication endpoints under /auth. Single-owner product: the first registration
becomes the owner, after which registration is closed. Sessions are server-side cookies."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth import users as users_svc
from ...auth.deps import current_user
from ...auth.passwords import verify_password
from ...auth.sessions import COOKIE_NAME, SESSION_TTL_DAYS, create_session, revoke_session
from ...db import repo
from ...db.engine import get_session
from ...db.models import User

router = APIRouter(prefix="/auth", tags=["auth"])


class Credentials(BaseModel):
    email: str
    password: str


class ChangePassword(BaseModel):
    current_password: str
    new_password: str


def _set_cookie(response: Response, request: Request, sid: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sid,
        max_age=SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def _public(user: User) -> dict:
    return {"id": user.id, "email": user.email, "display_name": user.display_name, "role": user.role}


@router.post("/register")
async def register(
    creds: Credentials, request: Request, response: Response, session: AsyncSession = Depends(get_session)
):
    # Owner bootstrap: open only while there are zero users (single-owner instance).
    if await repo.count_users(session) > 0:
        raise HTTPException(403, "Registration is closed (single-owner instance).")
    if len(creds.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    try:
        user = await users_svc.register_user(session, creds.email, creds.password, role="owner")
        await session.flush()
    except IntegrityError:
        # Lost a race / duplicate email — the DB single-owner index or unique email rejected it.
        await session.rollback()
        raise HTTPException(403, "Registration is closed (single-owner instance).") from None
    sid = (await create_session(session, user.id, request.headers.get("user-agent"))).id
    _set_cookie(response, request, sid)
    return _public(user)


@router.post("/login")
async def login(
    creds: Credentials, request: Request, response: Response, session: AsyncSession = Depends(get_session)
):
    user = await users_svc.authenticate(session, creds.email, creds.password)
    if user is None:
        raise HTTPException(401, "Invalid email or password.")
    sid = (await create_session(session, user.id, request.headers.get("user-agent"))).id
    _set_cookie(response, request, sid)
    return _public(user)


@router.post("/logout")
async def logout(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    await revoke_session(session, request.cookies.get(COOKIE_NAME))
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
async def me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    prof = await repo.ensure_profile(session, user.id)
    return {
        **_public(user),
        "profile": {
            "explain_mode": prof.explain_mode,
            "onboarded": prof.onboarded,
            "benchmark": prof.benchmark,
            "prefs": prof.prefs,
            "feature_flags": prof.feature_flags,
        },
    }


@router.get("/status")
async def status(session: AsyncSession = Depends(get_session)):
    """Unauthenticated bootstrap probe for the SPA: does an owner exist yet?"""
    return {"needs_setup": (await repo.count_users(session)) == 0}


@router.post("/change-password")
async def change_password(
    body: ChangePassword, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "Current password is incorrect.")
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    await users_svc.set_password(session, user, body.new_password)
    return {"ok": True}
