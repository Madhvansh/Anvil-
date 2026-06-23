"""Daily brief, "what changed", human-readable calibration, and the owner daily-cycle trigger."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ...auth.deps import current_user
from ...config import SUPPORTED_INDEXES
from ...db.models import User
from ...engine.brief import daily_brief
from ...engine.event_risk import event_risk
from ...engine.whatchanged import what_changed
from ..deps import cached_analyze

router = APIRouter(prefix="/api", tags=["brief"])


def _baseline(underlying: str, before_ts: str | None) -> dict | None:
    try:
        from ...store import SnapshotStore

        store = SnapshotStore()
        base = store.latest_payload(underlying.upper(), before_ts=before_ts)
        store.close()
        return base
    except Exception:  # noqa: BLE001 - store optional
        return None


def _calibration_human() -> dict:
    """Shape the ledger's per-class metrics into a human trust read."""
    try:
        from ...ledger.ledger import CalibrationLedger

        led = CalibrationLedger()
        by_class = led.metrics_by_class()
        led.close()
    except Exception:  # noqa: BLE001
        return {"headline": "Calibration sample still building.", "by_class": {}}

    live = by_class.get("live", {}).get("calibration_score", {})
    bt = by_class.get("backtest", {}).get("calibration_score", {})
    if live.get("score") is not None:
        headline = f"Live calibration {live['score']}/100 ({live['rating']}, n={live['n']}) — {live['reading']}"
    elif bt.get("score") is not None:
        headline = f"Backtested calibration {bt['score']}/100 ({bt['rating']}, n={bt['n']}); live track record still accruing."
    else:
        n = (live.get("n") or 0) + (bt.get("n") or 0)
        headline = f"Calibration sample still building (n={n}). It shows a score only once trustworthy."
    return {"headline": headline, "by_class": by_class}


@router.get("/calibration")
def calibration():
    return _calibration_human()


@router.get("/what-changed/{underlying}")
def what_changed_route(underlying: str, expiry: str | None = None):
    payload, _ = cached_analyze(underlying, expiry)
    baseline = _baseline(underlying, payload.get("timestamp"))
    return what_changed(payload, baseline)


@router.get("/daily-brief/{underlying}")
def daily_brief_route(underlying: str, expiry: str | None = None):
    payload, ch = cached_analyze(underlying, expiry)
    event = event_risk(ch)
    cal = _calibration_human()
    changed = what_changed(payload, _baseline(underlying, payload.get("timestamp")))
    return daily_brief(payload, event=event, calibration=cal, changed=changed)


class DailyRunBody(BaseModel):
    underlyings: list[str] | None = None
    realized: dict[str, float] | None = None
    as_of: str | None = None


@router.post("/daily/run")
def daily_run(body: DailyRunBody | None = None, user: User = Depends(current_user)):
    if user.role != "owner":
        raise HTTPException(403, "Only the owner can run the daily cycle.")
    from ...live.cycle import run_daily_cycle

    body = body or DailyRunBody()
    underlyings = body.underlyings or SUPPORTED_INDEXES
    return run_daily_cycle(underlyings, realized=body.realized, as_of=body.as_of)
