"""Calibration ledger endpoints (the moat). Writes fetch fresh data (not the cache) so
forecasts are recorded against the chain at record time. Synthetic seed/demo forecasts are
excluded from the public curves by construction (see ledger.PUBLIC_CLASSES)."""

from __future__ import annotations

from fastapi import APIRouter

from ..deps import DISCLAIMER, get_source

router = APIRouter(prefix="/api", tags=["ledger"])


@router.post("/ledger/record/{underlying}")
def ledger_record(underlying: str, expiry: str | None = None):
    from ...engine.implied_dist import implied_distribution
    from ...ledger.ledger import CalibrationLedger, emit_forecasts

    conn = get_source()
    ch = conn.get_chain(underlying, expiry)
    # Tag with the connector name so demo data is class "demo" (excluded from the public
    # curve) and a real source (upstox/groww/…) is class "live".
    fs = emit_forecasts(ch, implied_distribution(ch), source=conn.name)
    led = CalibrationLedger()
    led.record_many(fs)
    led.close()
    return {
        "recorded": len(fs),
        "underlying": ch.underlying,
        "resolve_ts": ch.expiry,
        "source": conn.name,
        "forecasts": [{"kind": f.kind, "params": f.params, "prob": f.prob} for f in fs],
        "disclaimer": DISCLAIMER,
    }


@router.post("/ledger/resolve/{underlying}")
def ledger_resolve(underlying: str, realized: float, as_of: str | None = None):
    from ...ledger.ledger import CalibrationLedger

    led = CalibrationLedger()
    n = led.resolve_due(underlying.upper(), realized, as_of)
    led.close()
    return {"resolved": n, "underlying": underlying.upper(), "realized": realized}


@router.get("/ledger/report")
def ledger_report():
    """Per-class calibration: the Backtested (real EOD, out-of-sample) and Live (forward)
    reliability curves + Calibration Scores. Synthetic seed/demo forecasts never appear.
    ``calibrators`` adds the fitted per-target probability maps (OOF ECE before/after, abstain_tau)."""
    from ...calibration.store import CalibratorStore
    from ...ledger.ledger import CalibrationLedger

    led = CalibrationLedger()
    cstore = CalibratorStore()
    try:
        by_class = led.metrics_by_class()
        calibrators = cstore.all()
    finally:
        led.close()
        cstore.close()
    return {**by_class, "calibrators": calibrators, "disclaimer": DISCLAIMER}
