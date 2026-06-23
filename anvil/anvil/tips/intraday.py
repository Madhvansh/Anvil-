"""Realtime/intraday tip pass — the per-tick hook for the live engine.

Reuses the shared tip pipeline to turn ONE realtime chain tick into gated tips, records them to the
calibration ledger, and persists them. Resolution is deferred to the EOD cycle (held-to-expiry), so
the intraday path only ISSUES. Sub-3-min OI is REST polling at the engine's cadence — true
tick-resolution OI is not available on retail Indian APIs, so cadence is honest, not promised as
ticks. The full asyncio market-hours loop (``live.live_runner``) calls ``run_intraday`` each tick.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..ingest import get_connector
from ..ingest.base import attach_parity_forward
from ..ledger.ledger import CalibrationLedger
from .calibration import record_tip
from .eod import tip_source_for
from .pipeline import tips_for_chain
from .store import IssuedTipStore, TipValidationStore
from .types import HEADLINE, Tip


def intraday_tip_pass(
    chain, *, ledger: CalibrationLedger, validation_store: TipValidationStore,
    issued_store: IssuedTipStore, source: str, equity: float | None = None,
) -> list[Tip]:
    """Generate + gate + record + persist tips for ONE realtime chain tick. Returns the tips."""
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    ctx, _bucket, _signals, tips = tips_for_chain(
        chain, source=source, equity=equity, validation_store=validation_store)
    for tip in tips:
        record_tip(ledger, tip, spot=ctx.spot, forward=ctx.forward)
        issued_store.record(tip)
    return tips


def run_intraday(
    underlyings: list[str] | tuple[str, ...] = ("NIFTY",),
    *,
    connector=None,
    ledger: CalibrationLedger | None = None,
    validation_store: TipValidationStore | None = None,
    issued_store: IssuedTipStore | None = None,
    equity: float | None = None,
) -> dict:
    """One realtime pass over all underlyings (the hook a live loop calls each tick). Issues tips;
    resolution is the EOD cycle's job. Returns {source, issued, headline, watchlist}."""
    owns_led, owns_vs, owns_is = ledger is None, validation_store is None, issued_store is None
    conn = connector or get_connector()
    led = ledger or CalibrationLedger()
    vstore = validation_store or TipValidationStore()
    istore = issued_store or IssuedTipStore()
    src = tip_source_for(conn.name)
    try:
        out: list[Tip] = []
        for u in underlyings:
            chain = attach_parity_forward(conn.get_chain(u))
            out.extend(intraday_tip_pass(
                chain, ledger=led, validation_store=vstore, issued_store=istore,
                source=src, equity=equity))
        return {
            "source": src,
            "issued": len(out),
            "headline": [t.to_dict() for t in out if t.tier == HEADLINE],
            "watchlist": [t.to_dict() for t in out if t.tier != HEADLINE],
        }
    finally:
        if owns_led:
            led.close()
        if owns_vs:
            vstore.close()
        if owns_is:
            istore.close()
