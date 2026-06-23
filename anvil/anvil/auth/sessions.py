"""Server-side, revocable sessions. The cookie carries only an opaque random id; all
state (user, expiry, last-seen, revoked) lives in the DB so we can log out a device
instantly. Timestamps are coerced to aware-UTC on read (SQLite returns naive)."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Session as DbSession
from ..db.models import User, utcnow

COOKIE_NAME = "anvil_sid"
SESSION_TTL_DAYS = 30


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def create_session(
    session: AsyncSession, user_id: int, user_agent: str | None = None, ttl_days: int = SESSION_TTL_DAYS
) -> DbSession:
    row = DbSession(
        id=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=utcnow() + timedelta(days=ttl_days),
        user_agent=(user_agent or "")[:400] or None,
    )
    session.add(row)
    await session.flush()
    return row


async def resolve_session(session: AsyncSession, sid: str | None) -> User | None:
    if not sid:
        return None
    row = await session.get(DbSession, sid)
    if not row or row.revoked:
        return None
    if _aware(row.expires_at) <= datetime.now(timezone.utc):
        return None
    row.last_seen_at = utcnow()
    user = await session.get(User, row.user_id)
    return user if (user and user.is_active) else None


async def revoke_session(session: AsyncSession, sid: str | None) -> None:
    if not sid:
        return
    row = await session.get(DbSession, sid)
    if row:
        row.revoked = True
        await session.flush()
