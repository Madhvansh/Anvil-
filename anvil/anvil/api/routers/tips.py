"""Short-term tips API — the public surface of the tips engine.

Three reads, all behind login + the TIPS_ENABLED flag (``require_tips``):
  * ``GET /api/tips/{underlying}`` — live tips split into the edge-proven HEADLINE feed and the
    developing-signal WATCHLIST (headline is gated on MEASURED validation evidence, so it is often
    empty by design);
  * ``GET /api/tips/track-record`` — the issued-tip reliability curves + per-(structure,regime)
    validation cells (this is where "accuracy" is shown — measured, never asserted);
  * ``GET /api/tips/feed`` — recently issued, persisted tips (for the dashboard feed).

Candidate generation is CPU-bound and DuckDB reads are blocking, so each handler runs its work in a
threadpool. This is the sanctioned public projection of the (otherwise private) strategy engine.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.concurrency import run_in_threadpool

from ...auth.deps import require_personal_owner
from ...config import SETTINGS
from ...db.models import User
from ...engine.util import json_safe
from ...gating import personal_mode_armed
from ...ingest.base import attach_parity_forward
from ...ledger.ledger import CalibrationLedger
from ...tips.eod import tip_source_for
from ...tips.predict import predict_for_chain
from ...tips.store import IssuedTipStore, TipValidationStore
from ...tips.types import HEADLINE
from ..deps import TIP_DISCLAIMER, get_source, require_tips

router = APIRouter(prefix="/api/tips", tags=["tips"])


def _track_record() -> dict:
    from ...calibration.store import CalibratorStore

    led = CalibrationLedger()
    store = TipValidationStore()
    cstore = CalibratorStore()
    try:
        # json_safe: validation cells store NaN (under-sampled t_stat/dsr/pbo); Starlette serializes
        # with allow_nan=False and 500s on a NaN. Sanitize before it leaves the API.
        return json_safe({
            "by_class": led.metrics_for_tips(),
            "cells": store.all(),
            "calibrators": cstore.all(),  # per-target/class maps: kind, n, OOF ECE before/after, abstain_tau
            "disclaimer": TIP_DISCLAIMER,
        })
    finally:
        led.close()
        store.close()
        cstore.close()


@router.get("/track-record")
async def track_record(user: User = Depends(require_tips)):
    """Issued-tip reliability (tip_backtest + tip_live) + per-cell validation verdicts."""
    return await run_in_threadpool(_track_record)


def _trust_dial_payload() -> dict:
    from ...backtest.vrp_prior import run_vrp_prior
    from ...tips.trust_dial import build_trust_dial

    led = CalibrationLedger()
    vstore = TipValidationStore()
    istore = IssuedTipStore()
    try:
        vrp = run_vrp_prior()
        return json_safe(build_trust_dial(led=led, istore=istore, vstore=vstore,
                                          vrp_prior=(None if vrp.get("error") else vrp)))
    finally:
        led.close()
        vstore.close()
        istore.close()


@router.get("/trust-dial")
async def trust_dial(user: User = Depends(require_tips)):
    """The live trust dial (Phase 5): reliability curve + accuracy-at-coverage + coverage % + the
    tail-stats scorecard over resolved tips + per-cell verdicts + VRP-prior anchor + gate/armed
    status. Display-only — it never influences emission."""
    return await run_in_threadpool(_trust_dial_payload)


def _feed(underlying: str | None, tier: str | None, limit: int) -> dict:
    store = IssuedTipStore()
    try:
        return json_safe({"tips": store.recent(underlying=underlying, tier=tier, limit=limit),
                          "disclaimer": TIP_DISCLAIMER})
    finally:
        store.close()


@router.get("/feed")
async def feed(
    underlying: str | None = Query(default=None),
    tier: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    user: User = Depends(require_tips),
):
    """Recently issued, persisted tips (optionally filtered by underlying/tier)."""
    return await run_in_threadpool(_feed, underlying, tier, limit)


def _equities() -> dict:
    """Ranked single-stock BUY/SELL tips. Live by default (``stock_tips_live``): a dynamic universe
    (most-liquid + highest-momentum names) deep-analysed through the SAME full pipeline as the index
    — live chain greeks/IV/OI/skew/GEX + momentum — ranked cross-sectionally, TTL-cached, with an
    honest ``computed_ts``. Set ANVIL_STOCK_TIPS_LIVE=false to revert to the legacy nightly-store read."""
    if SETTINGS.stock_tips_live:
        from ...tips.stock_cache import get_stock_tips

        return json_safe(get_stock_tips())

    from ...tips.equities import EQUITY_STRUCTURE

    store = IssuedTipStore()
    led = CalibrationLedger()
    try:
        recent = store.recent(limit=400)
        seen: set[str] = set()
        latest: list[dict] = []
        for t in recent:  # recent() is created_ts DESC, so first per symbol is newest
            if t.get("structure") != EQUITY_STRUCTURE or t["underlying"] in seen:
                continue
            seen.add(t["underlying"])
            latest.append(t)
        buys = [t for t in latest if t["direction"] == "bullish"]
        sells = [t for t in latest if t["direction"] == "bearish"]
        return json_safe({
            "buys": sorted(buys, key=lambda t: -(t.get("conviction") or 0)),
            "sells": sorted(sells, key=lambda t: -(t.get("conviction") or 0)),
            "as_of": latest[0]["created_ts"] if latest else None,
            "tip_calibration": led.metrics_for_tips(),
            "disclaimer": TIP_DISCLAIMER,
        })
    finally:
        store.close()
        led.close()


@router.get("/equities")
async def equities(user: User = Depends(require_tips)):
    """Ranked single-stock BUY/SELL tips (cross-sectional momentum). EOD/swing horizon."""
    return await run_in_threadpool(_equities)


def _universe() -> dict:
    from ...config import SUPPORTED_INDEXES
    from ...tips.universe import cached_universe

    stocks = cached_universe() if SETTINGS.stock_tips_live else [
        s.strip().upper() for s in SETTINGS.stock_options_universe.split(",") if s.strip()]
    return {"indexes": SUPPORTED_INDEXES, "stocks": stocks}


@router.get("/universe")
async def universe(user: User = Depends(require_tips)):
    """The symbol picker's contents: the supported indices + the live dynamic single-stock universe
    (most-liquid + highest-momentum names) the tips/momentum tabs can analyse."""
    return await run_in_threadpool(_universe)


def _open(factory):
    """Open a DuckDB-backed store, degrading to None if it can't be opened (e.g. a cross-process
    writer holds the single-writer lock). The live prediction is always-present, so a missing overlay
    store just means fewer honesty overlays — never a 500."""
    try:
        return factory()
    except Exception:  # noqa: BLE001 - overlay store is best-effort; never sink the prediction
        return None


def _compute_tips(underlying: str, equity: float, owner_view: bool = False) -> dict:
    """Build the tips payload. ``owner_view`` (the Phase-4 wall) gates the actionable surface: when
    False (public default) the prediction is the ADR-0004-clean analytics projection and the sized
    HEADLINE/WATCHLIST feeds are withheld; when True the owner gets the full sized, risk-bearing read.

    Every overlay (validation store, calibration service, ledger metrics, meta-label) is best-effort:
    if its store is locked or a row is malformed it degrades to None/{} rather than 500-ing the
    never-empty live read."""
    from ...calibration.store import CalibratorStore
    from ...tips.meta_store import get_meta_label

    conn = get_source()
    chain = attach_parity_forward(conn.get_chain(underlying))
    src = tip_source_for(conn.name)
    store = _open(TipValidationStore)
    led = _open(CalibrationLedger)
    cstore = _open(CalibratorStore)
    try:
        tip_metrics = led.metrics_for_tips() if led is not None else {}
        calibration = None
        if cstore is not None and SETTINGS.calibration_enabled:
            try:
                calibration = cstore.load_service()
            except Exception:  # noqa: BLE001 - calibration is display-only; degrade to identity
                calibration = None
        try:
            meta_label = get_meta_label()
        except Exception:  # noqa: BLE001 - meta-label is an abstaining overlay
            meta_label = None

        ctx, bucket, signals, pred, tips = predict_for_chain(
            chain, source=src, equity=equity, validation_store=store, tip_metrics=tip_metrics,
            calibration=calibration, with_risk=owner_view, meta_label=meta_label)
    finally:
        for _s in (store, led, cstore):
            if _s is not None:
                _s.close()
    # Actionable, sized tip feeds are OWNER-only (legs/targets/₹ sizing). Public callers get none.
    headline = [t.to_dict() for t in tips if t.tier == HEADLINE] if owner_view else []
    watchlist = [t.to_dict() for t in tips if t.tier != HEADLINE] if owner_view else []
    return json_safe({
        "underlying": underlying.upper(),
        "spot": ctx.spot,
        "regime": ctx.regime.label,
        "regime_bucket": bucket,
        "prediction": pred.to_dict(owner=owner_view),  # ALWAYS present — never-empty live read
        "signals": [s.to_dict() for s in signals],
        "headline": headline,
        "watchlist": watchlist,
        "personal_mode": owner_view,  # whether the actionable/sized surface is armed for this caller
        "tip_calibration": tip_metrics,  # measured live reliability (honesty overlay)
        "source": src,
        "disclaimer": TIP_DISCLAIMER,
    })


@router.get("/{underlying}/actionable")
async def tips_actionable(underlying: str, user: User = Depends(require_personal_owner)):
    """OWNER-only actionable, sized tips + per-ticket risk distribution. Behind the Phase-4 hard wall
    (ADR 0006): requires ANVIL_PERSONAL_MODE + the owner, and is additionally gated on a passing
    Gate-0 — until the conviction cell clears the kill switch, even the owner gets analytics only."""
    if not personal_mode_armed():
        raise HTTPException(
            status_code=409,
            detail="Actionable sizing is gated until Gate-0 passes (no certified cell yet).",
        )
    return await run_in_threadpool(_compute_tips, underlying, float(SETTINGS.paper_starting_capital), True)


@router.get("/{underlying}")
async def tips_for(underlying: str, user: User = Depends(require_tips)):
    """Live short-term tips for ``underlying`` — PUBLIC analytics (calibrated read, regime, factors).
    Actionable sized tips are owner-only at ``/{underlying}/actionable`` (Phase-4 wall)."""
    owner_view = bool(SETTINGS.personal_mode) and user.role == "owner" and personal_mode_armed()
    return await run_in_threadpool(
        _compute_tips, underlying, float(SETTINGS.paper_starting_capital), owner_view)
