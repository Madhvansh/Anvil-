"""Single-leg Greeks endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..data.source import DataSource
from ..storage.duck import DuckStore
from ..storage.sqlite_meta import SqliteMeta
from . import service
from .deps import get_datasource, get_meta, get_store

router = APIRouter(tags=["greeks"])


@router.get("/greeks")
def get_greeks(
    strike: float,
    underlying: str = "NIFTY",
    option_type: str = "c",
    snapshot_id: str | None = None,
    source: DataSource = Depends(get_datasource),
    store: DuckStore = Depends(get_store),
    meta: SqliteMeta = Depends(get_meta),
):
    try:
        return service.get_leg_greeks(
            underlying, strike, option_type, snapshot_id, source=source, store=store, meta=meta
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {exc}") from exc
