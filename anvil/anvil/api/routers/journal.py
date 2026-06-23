"""Behavioral journal (gated): notes / trade reviews / bias flags, optionally linked to the
market context (a stored snapshot) so an entry shows what the regime looked like at the time."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import current_user
from ...db import repo
from ...db.engine import get_session
from ...db.models import User

router = APIRouter(prefix="/api", tags=["journal"])

_TYPES = ("note", "trade_review", "emotion", "bias_flag")


class JournalIn(BaseModel):
    text: str
    entry_type: str = "note"
    underlying: str | None = None
    tags: list[str] | None = None
    linked_snapshot_id: str | None = None
    sentiment: str | None = None


def _dict(e) -> dict:
    return {
        "id": e.id,
        "ts": e.ts.isoformat() if e.ts else None,
        "entry_type": e.entry_type,
        "underlying": e.underlying,
        "text": e.text,
        "tags": e.tags,
        "linked_snapshot_id": e.linked_snapshot_id,
        "sentiment": e.sentiment,
    }


@router.get("/journal")
async def list_journal(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [_dict(e) for e in await repo.list_journal_entries(session, user.id)]


@router.post("/journal")
async def add_journal(
    body: JournalIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)
):
    entry_type = body.entry_type if body.entry_type in _TYPES else "note"
    entry = await repo.create_journal_entry(
        session,
        user_id=user.id,
        entry_type=entry_type,
        text=body.text,
        underlying=body.underlying,
        tags=body.tags,
        linked_snapshot_id=body.linked_snapshot_id,
        sentiment=body.sentiment,
    )
    return _dict(entry)
