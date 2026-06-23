"""User service: registration + authentication over the repo layer."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..db import repo
from ..db.models import User
from .passwords import hash_password, verify_password


async def register_user(
    session: AsyncSession,
    email: str,
    password: str,
    *,
    display_name: str | None = None,
    role: str = "owner",
) -> User:
    user = await repo.create_user(
        session,
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        role=role,
    )
    await repo.ensure_profile(session, user.id)
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await repo.get_user_by_email(session, email)
    if user and user.is_active and verify_password(user.password_hash, password):
        return user
    return None


async def set_password(session: AsyncSession, user: User, new_password: str) -> None:
    user.password_hash = hash_password(new_password)
    await session.flush()
