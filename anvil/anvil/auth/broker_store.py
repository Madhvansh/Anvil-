"""Per-user broker tokens, encrypted at rest (Fernet). Multi-user-ready store backing
the broker-connect flow and connection status.

Note: the sync data connectors (ingest/*) still read the owner's token from the file
``TokenStore`` for the live data path — see ``ingest.get_connector``. This DB store is the
source of truth for connection *state* and the migration path to true multi-tenant.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import BrokerToken
from . import crypto


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _expired(row: BrokerToken) -> bool:
    exp = _aware(row.expires_at)
    return exp is not None and exp <= datetime.now(timezone.utc)


async def get_row(session: AsyncSession, user_id: int, broker: str) -> BrokerToken | None:
    res = await session.execute(
        select(BrokerToken).where(BrokerToken.user_id == user_id, BrokerToken.broker == broker)
    )
    return res.scalar_one_or_none()


async def save_token(
    session: AsyncSession,
    *,
    user_id: int,
    broker: str,
    access_token: str,
    expires_at: datetime | None = None,
    meta: dict | None = None,
) -> BrokerToken:
    enc = crypto.encrypt(access_token)
    if enc is None:
        raise RuntimeError("ANVIL_SECRET_KEY not set — refusing to store a broker token unencrypted.")
    row = await get_row(session, user_id, broker)
    if row is None:
        row = BrokerToken(
            user_id=user_id, broker=broker, access_token_enc=enc, expires_at=expires_at, meta=meta or {}
        )
        session.add(row)
    else:
        row.access_token_enc = enc
        row.expires_at = expires_at
        row.meta = meta or {}
        row.minted_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def get_token(session: AsyncSession, user_id: int, broker: str) -> str | None:
    row = await get_row(session, user_id, broker)
    if row is None or _expired(row):
        return None
    return crypto.decrypt(row.access_token_enc)


async def list_connections(session: AsyncSession, user_id: int) -> list[dict]:
    res = await session.execute(select(BrokerToken).where(BrokerToken.user_id == user_id))
    out: list[dict] = []
    for r in res.scalars().all():
        out.append(
            {
                "broker": r.broker,
                "connected": not _expired(r),
                "expires_at": _aware(r.expires_at).isoformat() if r.expires_at else None,
                "minted_at": _aware(r.minted_at).isoformat() if r.minted_at else None,
            }
        )
    return out
