"""The shared tip-generation sequence: factors → regime gate → candidates → gated tips.

This is the single source of truth used by the EOD cycle (``tips.eod``), the realtime intraday pass
(``tips.intraday``), and the API (``api.routers.tips``) — so the three live paths can never drift in
how a chain becomes tips. Pure of I/O except the optional validation-store read used by the gate.
"""

from __future__ import annotations

from ..factors import apply_regime_mask, classify_regime, compute_factors, fired_names
from ..strategy import TRADE, SignalContext, generate_candidates
from .build import tip_from_candidate
from .gate import apply_tier
from .types import Tip


def tips_for_chain(
    chain,
    *,
    source: str,
    equity: float,
    validation_store=None,
    created_ts: str | None = None,
    resolve_ts: str | None = None,
    safe_sizing: bool = False,
    series: dict | None = None,
) -> tuple[SignalContext, str, list, list[Tip]]:
    """Build gated tips from one chain. Returns (ctx, regime_bucket, signals, tips).

    Only ``action == TRADE`` candidates become tips. If ``validation_store`` is given, each tip's
    tier is set by the gate (headline iff MEASURED evidence supports it); otherwise tips keep the
    default WATCHLIST tier (used by the backtest, which measures rather than gates).

    ``safe_sizing`` turns on the Phase-4 honest-sizing safeguards (cost-adjusted Kelly, CVaR/margin
    caps, short-vol Kelly cap, measured-edge shrink). It is ON for the live tip/prediction path and
    OFF for the backtest, so certified cells (which use units-independent return-on-risk) are
    unaffected while the sizes we'd actually deploy are honest.

    ``series`` is the optional time-series block (``closes``/``bars_by_tf``/``flow_series``/
    ``intraday_session``) the caller attaches so momentum/flow factors can fire; None => the legacy
    chain-only context (byte-identical)."""
    ctx = SignalContext(chain, source=source, **(series or {}))
    signals = compute_factors(ctx)
    bucket = classify_regime(ctx)
    apply_regime_mask(signals, bucket)
    fired = fired_names(signals)
    tips: list[Tip] = []
    for cand in generate_candidates(
        ctx, equity, safe_sizing=safe_sizing, validation_store=validation_store, regime_bucket=bucket
    ):
        if cand.action != TRADE:
            continue
        tip = tip_from_candidate(
            cand, ctx, fired, source=source, regime_bucket=bucket,
            created_ts=created_ts, resolve_ts=resolve_ts,
        )
        if validation_store is not None:
            apply_tier(tip, validation_store)
        tips.append(tip)
    return ctx, bucket, signals, tips
