"""Compute + persist a snapshot to the DuckDB time-series store (fetches fresh)."""

from __future__ import annotations

from fastapi import APIRouter

from ...pipeline import analyze_chain, to_snapshot
from ...store import SnapshotStore
from ..deps import get_source

router = APIRouter(prefix="/api", tags=["snapshot"])


@router.post("/snapshot/{underlying}")
def snapshot(underlying: str, expiry: str | None = None):
    conn = get_source()
    ch = conn.get_chain(underlying, expiry)
    payload = analyze_chain(ch, conn.get_positions() if conn.provides_positions else None, source=conn.name)
    snap = to_snapshot(payload)
    store = SnapshotStore()
    store.write(snap, payload, source=conn.name, chain=ch)
    n = store.count(underlying.upper())
    store.close()
    return {"written": True, "snapshots_for_underlying": n, "snapshot": snap.model_dump()}
