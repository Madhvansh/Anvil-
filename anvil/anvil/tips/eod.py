"""EOD / swing tip cycle — the nightly pass that issues tips and resolves matured ones.

Mirrors ``live.cycle.run_daily_cycle``: pull each underlying's chain, build the signal context,
classify+mask the regime, generate candidates, and ISSUE a tip per tradeable candidate. Each tip is
gated to headline/watchlist from the MEASURED validation store, recorded into the calibration ledger
(under ``tip_live`` for real connectors, ``demo`` for synthetic — kept off the public tip curve), and
persisted (with legs) so it can be RESOLVED held-to-expiry on a later cycle when its expiry settles.

Idempotent: tip ids are content-hashed (anchored to the 15:30 close), ledger inserts are no-ops on
re-record, and the issued store is keyed by tip_id — re-running a day changes nothing.
"""

from __future__ import annotations

from ..config import SETTINGS
from ..ingest import get_connector
from ..ledger.ledger import CalibrationLedger
from .calibration import record_tip
from .pipeline import tips_for_chain
from .resolve import terminal_payoff
from .series import build_series_block
from .store import IssuedTipStore, TipValidationStore
from .types import HEADLINE

_SYNTHETIC = {"demo", "seed"}


def tip_source_for(connector_name: str) -> str:
    """Real connectors → 'tip_live' (public tip curve); synthetic demo/seed → 'demo' (excluded)."""
    return "demo" if (connector_name or "").lower() in _SYNTHETIC else "tip_live"


def run_tip_cycle(
    underlyings: list[str] | tuple[str, ...] = ("NIFTY",),
    *,
    connector=None,
    ledger: CalibrationLedger | None = None,
    validation_store: TipValidationStore | None = None,
    issued_store: IssuedTipStore | None = None,
    equity: float | None = None,
    realized: dict[str, float] | None = None,
    as_of: str | None = None,
    source: str | None = None,
    auto_resolve: bool = False,
) -> dict:
    owns_led, owns_vs, owns_is = ledger is None, validation_store is None, issued_store is None
    conn = connector or get_connector()
    led = ledger or CalibrationLedger()
    vstore = validation_store or TipValidationStore()
    istore = issued_store or IssuedTipStore()
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    src = source or tip_source_for(conn.name)
    try:
        tips_out = []
        cycle_day = ""
        for u in underlyings:
            ch = conn.get_chain(u)
            day = (ch.timestamp or "")[:10]
            if day:  # anchor to the close so same-day re-runs dedup exactly
                ch = ch.model_copy(update={"timestamp": f"{day}T15:30:00+05:30"})
                cycle_day = day
            ctx, _bucket, _signals, tips = tips_for_chain(
                ch, source=src, equity=equity, validation_store=vstore,
                series=build_series_block(u))
            for tip in tips:
                record_tip(led, tip, spot=ctx.spot, forward=ctx.forward)
                istore.record(tip)
                tips_out.append(tip)

        # Resolution: settle DUE tips (expiry on/before the as-of day) at the realized level.
        resolved: dict[str, int] = {}
        asof_day = (as_of or cycle_day or "")[:10]
        ts = f"{asof_day}T16:00:00+05:30" if asof_day else (as_of or "")
        # Auto-resolution (the Phase-5 keystone): when the operator didn't hand-feed realized closes,
        # fetch the PUBLISHED close for every underlying that has a DUE tip, so the moat clock accrues a
        # live track record on its own. Opt-in (default OFF) so the backtest/test paths are unchanged;
        # spot fallback OFF so we only ever resolve against a real published close (causal).
        if realized is None and auto_resolve and asof_day:
            from ..live.closes import realized_closes_for

            due_unds = [u for u in {x.upper() for x in underlyings} if istore.due_unresolved(u, asof_day)]
            realized = (
                realized_closes_for(due_unds, asof_day, connector=conn, allow_spot_fallback=False)
                if due_unds else {}
            )
        for u, level in (realized or {}).items():
            uu = u.upper()
            n = 0
            if not asof_day:
                resolved[uu] = 0
                continue
            for d in istore.due_unresolved(uu, asof_day):
                gross = terminal_payoff(d["legs"], int(d["lot_size"]), float(level))
                net = gross - float(d["round_trip_cost"])
                outcome = int(net > 0)
                ml = float(d.get("max_loss") or 0.0)
                ret = net / ml if ml > 0 else 0.0
                fid = d.get("ledger_forecast_id")
                if fid:
                    try:
                        led.resolve(fid, 1.0 if outcome else -1.0, resolved_ts=ts)
                    except KeyError:  # forecast not in this ledger (cross-ledger resolve) — skip
                        pass
                istore.mark_resolved(d["tip_id"], outcome, ts, net_pnl=net, ret=ret)
                n += 1
            resolved[uu] = n

        headline = [t.to_dict() for t in tips_out if t.tier == HEADLINE]
        watchlist = [t.to_dict() for t in tips_out if t.tier != HEADLINE]
        return {
            "source": src,
            "issued": len(tips_out),
            "resolved": resolved,
            "headline": headline,
            "watchlist": watchlist,
        }
    finally:
        if owns_led:
            led.close()
        if owns_vs:
            vstore.close()
        if owns_is:
            istore.close()
