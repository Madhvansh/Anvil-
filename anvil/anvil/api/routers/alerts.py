"""Alerts (gated): rule CRUD, fired-event feed, and an evaluate trigger that runs a user's
rules against the current analytics and records natural-language events."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.deps import current_user
from ...db import repo
from ...db.engine import get_session
from ...db.models import User
from ...engine.alerts import evaluate_rules

router = APIRouter(prefix="/api/alerts", tags=["alerts"])

_KINDS = (
    "price_band",
    "pcr_threshold",
    "gex_flip_cross",
    "oi_wall_break",
    "iv_crush",
    "event_risk",
    "unusual_activity",
)


class RuleIn(BaseModel):
    underlying: str
    kind: str
    params: dict = {}
    channel: dict = {}
    cooldown_s: int = 0


def _rule_dict(r) -> dict:
    return {
        "id": r.id,
        "underlying": r.underlying,
        "kind": r.kind,
        "params": r.params,
        "channel": r.channel,
        "enabled": r.enabled,
        "cooldown_s": r.cooldown_s,
    }


def _event_dict(e) -> dict:
    return {
        "id": e.id,
        "rule_id": e.rule_id,
        "underlying": e.underlying,
        "severity": e.severity,
        "title": e.title,
        "body": e.body,
        "payload": e.payload,
        "fired_at": e.fired_at.isoformat() if e.fired_at else None,
        "read_at": e.read_at.isoformat() if e.read_at else None,
    }


@router.get("")
async def list_rules(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [_rule_dict(r) for r in await repo.list_alert_rules(session, user.id)]


@router.post("")
async def create_rule(body: RuleIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if body.kind not in _KINDS:
        raise HTTPException(400, f"kind must be one of {_KINDS}")
    rule = await repo.create_alert_rule(
        session,
        user_id=user.id,
        underlying=body.underlying,
        kind=body.kind,
        params=body.params,
        channel=body.channel,
        cooldown_s=body.cooldown_s,
    )
    return _rule_dict(rule)


@router.delete("/{rule_id}")
async def delete_rule(rule_id: int, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not await repo.delete_alert_rule(session, user.id, rule_id):
        raise HTTPException(404, "Rule not found")
    return {"deleted": rule_id}


@router.get("/events")
async def list_events(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return [_event_dict(e) for e in await repo.list_alert_events(session, user.id)]


@router.post("/evaluate/{underlying}")
async def evaluate(underlying: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    """Run the user's rules for one underlying against fresh analytics; record fired events."""
    from ..deps import cached_analyze

    rules = [_rule_dict(r) for r in await repo.list_alert_rules(session, user.id, underlying)]
    if not rules:
        return {"fired": [], "evaluated": 0}

    payload, ch = cached_analyze(underlying, None)
    extras = _extras(ch, rules)
    prev = _baseline(underlying, payload.get("timestamp"))

    fired = []
    for ev in evaluate_rules(rules, payload, prev=prev, extras=extras):
        rid = ev.get("rule_id")
        cooldown = next((r["cooldown_s"] for r in rules if r["id"] == rid), 0)
        if rid and await repo.rule_recently_fired(session, user.id, rid, cooldown):
            continue
        row = await repo.create_alert_event(
            session,
            user_id=user.id,
            rule_id=rid,
            underlying=ev["underlying"],
            severity=ev["severity"],
            title=ev["title"],
            body=ev["body"],
            payload=ev["detail"],
        )
        fired.append(_event_dict(row))
    return {"fired": fired, "evaluated": len(rules)}


def _extras(ch, rules: list[dict]) -> dict:
    kinds = {r["kind"] for r in rules}
    extras: dict = {}
    if "iv_crush" in kinds:
        from ...engine.iv_crush import iv_crush_warning

        extras["iv_crush"] = iv_crush_warning(ch)
    if "event_risk" in kinds:
        from ...engine.event_risk import event_risk

        extras["event_risk"] = event_risk(ch)
    if "unusual_activity" in kinds:
        from ...engine.unusual import unusual_activity

        extras["unusual"] = unusual_activity(ch)
    return extras


def _baseline(underlying: str, before_ts: str | None) -> dict | None:
    try:
        from ...store import SnapshotStore

        store = SnapshotStore()
        base = store.latest_payload(underlying.upper(), before_ts=before_ts)
        store.close()
        return base
    except Exception:  # noqa: BLE001
        return None
