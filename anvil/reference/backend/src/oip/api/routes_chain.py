"""Chain endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..data.source import DataSource
from ..storage.duck import DuckStore
from ..storage.sqlite_meta import SqliteMeta
from . import service
from .deps import get_datasource, get_meta, get_store

router = APIRouter(tags=["chain"])


@router.get("/chain")
def get_chain(
    underlying: str = "NIFTY",
    snapshot_id: str | None = None,
    source: DataSource = Depends(get_datasource),
    store: DuckStore = Depends(get_store),
    meta: SqliteMeta = Depends(get_meta),
):
    try:
        return service.get_chain_view(underlying, snapshot_id, source=source, store=store, meta=meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {exc}") from exc


@router.get("/chain/{snapshot_id}")
def get_chain_by_id(
    snapshot_id: str,
    source: DataSource = Depends(get_datasource),
    store: DuckStore = Depends(get_store),
    meta: SqliteMeta = Depends(get_meta),
):
    try:
        return service.get_chain_view("", snapshot_id, source=source, store=store, meta=meta)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {exc}") from exc
