"""Read-only analytics endpoints. gex/implied-dist read from the same cached analyze
payload (those slices don't depend on positions), so one chain fetch serves all three."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..deps import DISCLAIMER, cached_analyze, get_source, source_status

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/source/status")
def source_status_endpoint(underlying: str = "NIFTY"):
    """Is this instance live or on demo data, and — if demo — exactly why. The UI polls this to
    flip the LIVE/DEMO badge and show an actionable reason. No secrets are returned."""
    return source_status(underlying)


@router.get("/chain/{underlying}")
def chain(underlying: str, expiry: str | None = None):
    conn = get_source()
    if not conn.provides_chain:
        raise HTTPException(400, f"Source {conn.name} has no chain. Use upstox/dhan/demo.")
    return conn.get_chain(underlying, expiry).model_dump()


@router.get("/analyze/{underlying}")
def analyze(underlying: str, expiry: str | None = None):
    payload, _ = cached_analyze(underlying, expiry)
    return {**payload, "disclaimer": DISCLAIMER}


@router.get("/gex/{underlying}")
def gex(underlying: str, expiry: str | None = None):
    payload, _ = cached_analyze(underlying, expiry)
    return payload["gex"]


@router.get("/implied-dist/{underlying}")
def implied_dist(underlying: str, expiry: str | None = None):
    payload, _ = cached_analyze(underlying, expiry)
    return payload["implied_distribution"]
