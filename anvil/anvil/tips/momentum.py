"""Momentum prediction surface — foregrounds the multi-timeframe + options-flow momentum read for one
underlying (stock OR index), built on the SAME prediction spine so it can never drift.

It attaches the time-series block (``tips.series.build_series_block``) to the chain, runs
``predict_for_chain`` (so momentum/flow factors fire into conviction and any gated tip), then surfaces
the momentum read explicitly: the consensus ``MomentumRead``, the options-flow ``FlowMomentumRead``, the
fired momentum factors, and the resulting (honestly-gated) prediction. No new accuracy claim — momentum
is an *agreement/velocity* read; whether it becomes an actionable tip is decided by the locked gate.
"""

from __future__ import annotations

from ..factors.momentum import (
    EXPIRY_LAST30,
    GEX_FLIP,
    INTRADAY_ORVWAP,
    IV_RANK_VEL,
    MTF_TREND,
    OI_VELOCITY,
)
from .predict import predict_for_chain
from .series import build_series_block

MOMENTUM_FACTORS = {MTF_TREND, OI_VELOCITY, GEX_FLIP, IV_RANK_VEL, INTRADAY_ORVWAP, EXPIRY_LAST30}


def _read_to_dict(read) -> dict | None:
    if read is None:
        return None
    to_dict = getattr(read, "to_dict", None)
    return to_dict() if callable(to_dict) else None


def momentum_for_chain(
    chain, *, source: str, equity: float, bar_store=None, snap_store=None,
    validation_store=None, series: dict | None = None,
) -> dict:
    """Momentum read + prediction for one chain. ``series`` may be supplied directly (e.g. a replay);
    otherwise it is built from Yahoo closes + the injected bar/snap stores. Returns a JSON-able dict."""
    from .meta_store import get_meta_label

    block = series if series is not None else build_series_block(
        chain.underlying, bar_store=bar_store, snap_store=snap_store)
    ctx, bucket, signals, pred, tips = predict_for_chain(
        chain, source=source, equity=equity, validation_store=validation_store, series=block,
        meta_label=get_meta_label())

    mom_factors = [s.to_dict() for s in signals if s.name in MOMENTUM_FACTORS]
    return {
        "underlying": ctx.underlying,
        "as_of": ctx.timestamp or "",
        "spot": ctx.spot,
        "regime_bucket": bucket,
        "momentum": _read_to_dict(ctx.momentum),
        "flow": _read_to_dict(ctx.flow),
        "momentum_factors": mom_factors,
        "timeframes": sorted((block.get("bars_by_tf") or {}).keys()),
        "has_series": bool(block),
        "prediction": pred.to_dict(),
    }
