"""Analytics + calibration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from ..calibration.ledger import CalibrationLedger
from ..data.source import DataSource
from . import analytics_service
from .deps import get_datasource, get_ledger

router = APIRouter(tags=["analytics"])


@router.get("/analytics/{underlying}")
def analytics(underlying: str, source: DataSource = Depends(get_datasource)):
    try:
        return analytics_service.get_analytics_view(underlying, source=source)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/calibration")
def calibration(
    underlying: str | None = None,
    ledger: CalibrationLedger = Depends(get_ledger),
):
    return analytics_service.get_calibration_summary(underlying, ledger=ledger)
