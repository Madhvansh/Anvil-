"""Thin repository layer over the ORM. Routers depend on these helpers, never on raw
SQL or the session internals. Functions take an ``AsyncSession`` and flush (not commit);
the request-scoped session (``engine.get_session``) commits once at the end.

Grows per milestone — M1 lands the user/profile/watchlist core that proves the spine.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timedelta, timezone

from .models import AlertEvent, AlertRule, JournalEntry, User, UserProfile, Watchlist


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str | None = None,
    role: str = "owner",
) -> User:
    user = User(email=email.strip().lower(), password_hash=password_hash, display_name=display_name, role=role)
    session.add(user)
    await session.flush()  # assign user.id without ending the request transaction
    return user


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    res = await session.execute(select(User).where(User.email == email.strip().lower()))
    return res.scalar_one_or_none()


async def count_users(session: AsyncSession) -> int:
    res = await session.execute(select(func.count()).select_from(User))
    return int(res.scalar_one())


async def ensure_profile(session: AsyncSession, user_id: int) -> UserProfile:
    """Get the user's profile, creating it with all features unlocked (no tiers) if absent."""
    prof = await session.get(UserProfile, user_id)
    if prof is None:
        prof = UserProfile(user_id=user_id, feature_flags={"all": True})
        session.add(prof)
        await session.flush()
    return prof


async def add_watchlist(
    session: AsyncSession,
    *,
    user_id: int,
    name: str,
    symbols: list[str],
    is_default: bool = False,
) -> Watchlist:
    wl = Watchlist(user_id=user_id, name=name, symbols=list(symbols), is_default=is_default)
    session.add(wl)
    await session.flush()
    return wl


async def list_watchlists(session: AsyncSession, user_id: int) -> list[Watchlist]:
    res = await session.execute(
        select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.id)
    )
    return list(res.scalars().all())


async def get_watchlist(session: AsyncSession, user_id: int, wl_id: int) -> Watchlist | None:
    wl = await session.get(Watchlist, wl_id)
    return wl if (wl and wl.user_id == user_id) else None


async def delete_watchlist(session: AsyncSession, user_id: int, wl_id: int) -> bool:
    wl = await get_watchlist(session, user_id, wl_id)
    if wl is None:
        return False
    await session.delete(wl)
    await session.flush()
    return True


_PROFILE_FIELDS = {"explain_mode", "benchmark", "onboarded", "prefs", "feature_flags"}


async def update_profile(session: AsyncSession, user_id: int, **fields) -> UserProfile:
    prof = await ensure_profile(session, user_id)
    for key, value in fields.items():
        if value is not None and key in _PROFILE_FIELDS:
            setattr(prof, key, value)
    await session.flush()
    return prof


async def create_journal_entry(
    session: AsyncSession,
    *,
    user_id: int,
    entry_type: str,
    text: str,
    underlying: str | None = None,
    tags: list | None = None,
    linked_snapshot_id: str | None = None,
    sentiment: str | None = None,
) -> JournalEntry:
    entry = JournalEntry(
        user_id=user_id,
        entry_type=entry_type,
        text=text,
        underlying=underlying,
        tags=tags,
        linked_snapshot_id=linked_snapshot_id,
        sentiment=sentiment,
    )
    session.add(entry)
    await session.flush()
    return entry


async def list_journal_entries(session: AsyncSession, user_id: int, limit: int = 100) -> list[JournalEntry]:
    res = await session.execute(
        select(JournalEntry)
        .where(JournalEntry.user_id == user_id)
        .order_by(JournalEntry.ts.desc())
        .limit(limit)
    )
    return list(res.scalars().all())


# --- Alerts -------------------------------------------------------------------------


async def create_alert_rule(
    session: AsyncSession,
    *,
    user_id: int,
    underlying: str,
    kind: str,
    params: dict | None = None,
    channel: dict | None = None,
    cooldown_s: int = 0,
) -> AlertRule:
    rule = AlertRule(
        user_id=user_id,
        underlying=underlying.upper(),
        kind=kind,
        params=params or {},
        channel=channel or {},
        cooldown_s=cooldown_s,
    )
    session.add(rule)
    await session.flush()
    return rule


async def list_alert_rules(session: AsyncSession, user_id: int, underlying: str | None = None) -> list[AlertRule]:
    q = select(AlertRule).where(AlertRule.user_id == user_id)
    if underlying:
        q = q.where(AlertRule.underlying == underlying.upper())
    res = await session.execute(q.order_by(AlertRule.id))
    return list(res.scalars().all())


async def delete_alert_rule(session: AsyncSession, user_id: int, rule_id: int) -> bool:
    rule = await session.get(AlertRule, rule_id)
    if rule is None or rule.user_id != user_id:
        return False
    await session.delete(rule)
    await session.flush()
    return True


async def rule_recently_fired(session: AsyncSession, user_id: int, rule_id: int, cooldown_s: int) -> bool:
    if cooldown_s <= 0:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=cooldown_s)
    res = await session.execute(
        select(AlertEvent.id)
        .where(AlertEvent.user_id == user_id, AlertEvent.rule_id == rule_id, AlertEvent.fired_at >= cutoff)
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


async def create_alert_event(
    session: AsyncSession,
    *,
    user_id: int,
    rule_id: int | None,
    underlying: str,
    severity: str,
    title: str,
    body: str | None = None,
    payload: dict | None = None,
) -> AlertEvent:
    ev = AlertEvent(
        user_id=user_id,
        rule_id=rule_id,
        underlying=underlying.upper(),
        severity=severity,
        title=title,
        body=body,
        payload=payload or {},
    )
    session.add(ev)
    await session.flush()
    return ev


async def list_alert_events(session: AsyncSession, user_id: int, limit: int = 50) -> list[AlertEvent]:
    res = await session.execute(
        select(AlertEvent).where(AlertEvent.user_id == user_id).order_by(AlertEvent.fired_at.desc()).limit(limit)
    )
    return list(res.scalars().all())
