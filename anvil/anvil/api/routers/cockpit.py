"""Cockpit status API (Wave 0) — the one freshness/health read for the unified live cockpit.

``GET /api/cockpit/status`` returns: the SPA build stamp (so the header can warn on a stale front-end),
the LiveSupervisor heartbeat (mode/last-run/market-open), the gate/personal-mode chip
(``gate0_passed``/``personal_mode_armed``), the resolved data source, and the freshest recorded snapshot
timestamp across the cockpit underlyings. Behind login; DuckDB read runs in a threadpool.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from starlette.concurrency import run_in_threadpool

from ...auth.deps import current_user
from ...config import SETTINGS
from ...db.models import User
from ...gating import gate0_passed, personal_mode_armed
from ...live.supervisor import get_supervisor
from ..buildinfo import build_stamp

router = APIRouter(prefix="/api/cockpit", tags=["cockpit"])


def _freshest_snapshot_ts() -> str | None:
    from ...store.timeseries import SnapshotStore

    freshest: str | None = None
    try:
        st = SnapshotStore()
        try:
            for u in [x.strip().upper() for x in SETTINGS.cockpit_underlyings.split(",") if x.strip()]:
                rows = st.latest(u, 1)
                if rows and rows[0] and rows[0][0] and (freshest is None or rows[0][0] > freshest):
                    freshest = rows[0][0]
        finally:
            st.close()
    except Exception:  # noqa: BLE001 - status must never raise
        return None
    return freshest


def _status() -> dict:
    sup = get_supervisor()
    sup_status = sup.status() if sup is not None else {"running": False}
    return {
        "build": build_stamp(),
        "supervisor": sup_status,
        "supervisor_running": bool(sup_status.get("running")),
        "gate0_passed": gate0_passed(),
        "personal_mode_armed": personal_mode_armed(),
        "source": SETTINGS.primary_data_source,
        "cockpit_underlyings": [x.strip().upper() for x in SETTINGS.cockpit_underlyings.split(",") if x.strip()],
        "freshest_snapshot_ts": _freshest_snapshot_ts(),
    }


@router.get("/status")
async def cockpit_status(user: User = Depends(current_user)):
    """Build stamp + supervisor heartbeat + gate/personal chip + freshest snapshot (logged-in)."""
    return await run_in_threadpool(_status)
