"""High-value analytics endpoints.

Market analytics (event-risk, IV-crush, unusual, participant-OI) are public within the instance.
Scenario grid and Monte Carlo are **gated** — they reprice the user's book, so they surface
position-derived P&L. All numeric payloads are NaN-sanitized before serialization."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ...auth.deps import current_user
from ...db.models import User
from ...engine.event_risk import event_risk
from ...engine.iv_crush import iv_crush_warning
from ...engine.montecarlo import mc_pnl
from ...engine.participant_oi import participant_oi_read
from ...engine.provenance import provenance
from ...engine.scenarios import scenario_grid
from ...engine.unusual import unusual_activity
from ...engine.util import json_safe
from ...engine.vol import term_structure
from ..deps import get_source, source_chain_positions

router = APIRouter(prefix="/api", tags=["advanced"])


@router.get("/scenario/{underlying}")
def scenario(underlying: str, expiry: str | None = None, horizon_days: float = 0.0, user: User = Depends(current_user)):
    conn, ch, positions = source_chain_positions(underlying, expiry)
    out = scenario_grid(ch, positions, horizon_days=horizon_days)
    out["provenance"] = provenance(ch, source=conn.name, derived_from="scenario_grid")
    return json_safe(out)


class MCBody(BaseModel):
    horizon_days: float = 7.0
    n_paths: int = 10000
    seed: int | None = None


@router.post("/montecarlo/{underlying}")
def montecarlo(underlying: str, body: MCBody | None = None, expiry: str | None = None, user: User = Depends(current_user)):
    body = body or MCBody()
    conn, ch, positions = source_chain_positions(underlying, expiry)
    out = mc_pnl(ch, positions, horizon_days=body.horizon_days, n_paths=body.n_paths, seed=body.seed)
    out["provenance"] = provenance(ch, source=conn.name, derived_from="monte_carlo")
    return json_safe(out)


@router.get("/event-risk/{underlying}")
def event_risk_route(underlying: str, expiry: str | None = None):
    conn = get_source()
    ch = conn.get_chain(underlying, expiry)
    out = event_risk(ch)
    out["provenance"] = provenance(ch, source=conn.name, derived_from="event_risk")
    return json_safe(out)


@router.get("/iv-crush/{underlying}")
def iv_crush_route(underlying: str, expiry: str | None = None):
    conn = get_source()
    ch = conn.get_chain(underlying, expiry)
    out = iv_crush_warning(ch, history_iv=_iv_history(underlying), front_back=_front_back(conn, underlying))
    out["provenance"] = provenance(ch, source=conn.name, derived_from="iv_crush")
    return json_safe(out)


@router.get("/unusual/{underlying}")
def unusual_route(underlying: str, expiry: str | None = None):
    conn = get_source()
    ch = conn.get_chain(underlying, expiry)
    out = unusual_activity(ch)
    out["provenance"] = provenance(ch, source=conn.name, derived_from="unusual_activity")
    return json_safe(out)


@router.get("/participant-oi/{underlying}")
def participant_oi_route(underlying: str, date: str | None = None):
    # underlying accepted for URL symmetry; participant OI is market-wide (index F&O).
    return json_safe(participant_oi_read(date=date))


def _iv_history(underlying: str) -> list[float] | None:
    try:
        from ...store import SnapshotStore

        store = SnapshotStore()
        hist = store.iv_history(underlying.upper())
        store.close()
        return hist or None
    except Exception:  # noqa: BLE001 - store optional; degrade
        return None


def _front_back(conn, underlying: str) -> tuple[float, float] | None:
    try:
        exps = conn.get_expiries(underlying) if hasattr(conn, "get_expiries") else []
        if len(exps) < 2:
            return None
        chains = [conn.get_chain(underlying, e) for e in exps[:2]]
        ts = term_structure(chains)
        a, b = ts[0]["atm_iv"], ts[1]["atm_iv"]
        return (a, b) if (a and b) else None
    except Exception:  # noqa: BLE001
        return None
