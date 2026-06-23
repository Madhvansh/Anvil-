"""Daily cycle — the moat clock + the time-series moat in one pass.

Extends the bare forecast loop (``live.daily.run_daily``): for each underlying it also writes
a provenance-stamped analytics snapshot to the store, so the "what changed since yesterday"
diff and IV history have data to work with. Idempotent: forecast ids are content-hashed and
snapshots are keyed by (underlying, expiry, timestamp, source) — re-running a day is a no-op.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ..config import SETTINGS
from ..engine.implied_dist import implied_distribution
from ..ingest import get_connector
from ..ledger.ledger import CalibrationLedger, emit_forecasts
from ..pipeline import analyze_chain, to_snapshot
from ..store import SnapshotStore


def _refit_calibrators(ledger: CalibrationLedger, as_of: str | None) -> dict:
    """Refit + persist all per-(target, source-class) calibrators from accrued resolved history.
    Resilient: a calibration failure must never sink the daily cycle."""
    from ..backtest.trials import TrialRegistry
    from ..calibration.service import fit_all_targets
    from ..calibration.store import CalibratorStore

    now_ts = as_of or datetime.now(timezone.utc).isoformat()
    store = CalibratorStore()
    trials = TrialRegistry()
    try:
        return fit_all_targets(
            ledger=ledger, store=store, min_samples=SETTINGS.calibration_min_samples,
            blend_floor_n=SETTINGS.calibration_blend_floor_n,
            accuracy_floor=SETTINGS.calibration_accuracy_floor,
            n_splits=SETTINGS.calibration_n_splits, now_ts=now_ts, trial_registry=trials)
    except Exception as exc:  # noqa: BLE001 - calibration must never break the moat clock
        return {"error": str(exc)}
    finally:
        store.close()
        trials.close()


def run_daily_cycle(
    underlyings: list[str] | tuple[str, ...] = ("NIFTY",),
    *,
    connector=None,
    store: SnapshotStore | None = None,
    ledger: CalibrationLedger | None = None,
    realized: dict[str, float] | None = None,
    as_of: str | None = None,
    record_tips: bool = True,
    auto_resolve: bool = False,
) -> dict:
    owns_store = store is None
    owns_ledger = ledger is None
    conn = connector or get_connector()
    st = store or SnapshotStore()
    led = ledger or CalibrationLedger()
    src = conn.name
    try:
        recorded: dict[str, int] = {}
        snapped: dict[str, str] = {}
        cycle_day = ""
        for u in underlyings:
            ch = conn.get_chain(u)
            day = (ch.timestamp or "")[:10]
            if day:  # anchor to the close so same-day re-runs dedup exactly
                ch = ch.model_copy(update={"timestamp": f"{day}T15:30:00+05:30"})
                cycle_day = day
            payload = analyze_chain(ch, conn.get_positions() if conn.provides_positions else None, source=src)
            snap = to_snapshot(payload)
            snapped[u] = st.write(snap, payload, source=src, chain=ch)
            dist = implied_distribution(ch)
            recorded[u] = led.record_many(emit_forecasts(ch, dist, source=src)) if dist else 0

        # Auto-resolution (Phase-5 keystone): fetch the published close so forecasts AND tips resolve
        # themselves and the moat clock accrues forward. Opt-in; spot fallback OFF (causal). Explicit
        # `realized` always wins (tests / `--realized`). The same map is threaded to the tip cycle.
        rday = (as_of or cycle_day or "")[:10]
        if realized is None and auto_resolve and rday:
            from .closes import realized_closes_for

            realized = realized_closes_for(
                [u.upper() for u in underlyings], rday, connector=conn, allow_spot_fallback=False)

        resolved: dict[str, int] = {}
        for u, level in (realized or {}).items():
            resolved[u.upper()] = led.resolve_due(u.upper(), float(level), as_of)

        out = {"source": src, "recorded": recorded, "resolved": resolved, "snapshots": snapped}

        # Same nightly pass also issues + resolves short-term tips and re-validates the gate from
        # the accumulated live evidence, so the tips moat advances without a separate cron.
        if record_tips:
            from ..backtest.revalidate import revalidate_from_live
            from ..tips.eod import run_tip_cycle
            from ..tips.store import IssuedTipStore, TipValidationStore

            vstore, istore = TipValidationStore(), IssuedTipStore()
            try:
                tip_res = run_tip_cycle(
                    underlyings, connector=conn, ledger=led, validation_store=vstore,
                    issued_store=istore, realized=realized, as_of=as_of, auto_resolve=auto_resolve)
                reval = revalidate_from_live(issued_store=istore, validation_store=vstore)
                out["tips"] = {"issued": tip_res["issued"], "resolved": tip_res["resolved"]}
                out["revalidation"] = reval
                # Refit the meta-label (Innovation I.4) from the freshly-accrued resolved history and
                # persist it for the live predict path. Overlay — a failure never sinks the moat clock,
                # and a thin/single-class history just leaves the prior model in place (cold-start safe).
                try:
                    from ..tips.meta_features import train_from_store
                    from ..tips.meta_store import save as _save_meta

                    ml = train_from_store(istore)
                    if ml is not None:
                        _save_meta(ml)
                        out["meta_label"] = {"trained_n": ml.n}
                    else:
                        out["meta_label"] = {"trained_n": 0, "note": "insufficient_resolved_history"}
                except Exception as exc:  # noqa: BLE001 - meta-label is an overlay; never break the cycle
                    out["meta_label"] = {"error": str(exc)[:120]}
            finally:
                vstore.close()
                istore.close()

        # Same nightly pass refits the probability calibrators on the freshly-accrued resolved
        # history (per source-class), so the maps STRENGTHEN automatically as live tips resolve —
        # no separate cron. Calibration is display/threshold only; it never touches the gate verdict.
        if record_tips and SETTINGS.calibration_refit_enabled:
            out["calibration"] = _refit_calibrators(led, as_of)

        return out
    finally:
        if owns_ledger:
            led.close()
        if owns_store:
            st.close()
