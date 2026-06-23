"""Grounded copilot. Deterministic narration by default (mode-aware depth); optional Claude
Q&A only when ANTHROPIC_API_KEY is set, and every answer passes the compliance guardrail."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..deps import DISCLAIMER, cached_analyze

router = APIRouter(prefix="/api/copilot", tags=["copilot"])

_MODES = ("simple", "trader", "expert")


@router.get("/narrate/{underlying}")
def narrate(underlying: str, mode: str = "trader", expiry: str | None = None):
    from ...agent.analyst import GroundedAnalyst

    mode = mode if mode in _MODES else "trader"
    payload, _ = cached_analyze(underlying, expiry)
    return {"answer": GroundedAnalyst().narrate(payload, mode), "grounded": True, "mode": mode, "disclaimer": DISCLAIMER}


class AskBody(BaseModel):
    question: str
    mode: str = "trader"


@router.post("/ask/{underlying}")
def ask(underlying: str, body: AskBody, expiry: str | None = None):
    from ...agent.analyst import GroundedAnalyst

    payload, _ = cached_analyze(underlying, expiry)
    ledger_metrics = _ledger_metrics()
    result = GroundedAnalyst().ask(body.question, payload, ledger_metrics)
    result["disclaimer"] = DISCLAIMER
    return result


def _ledger_metrics() -> dict | None:
    try:
        from ...ledger.ledger import CalibrationLedger

        led = CalibrationLedger()
        m = led.metrics()
        led.close()
        return m
    except Exception:  # noqa: BLE001
        return None
