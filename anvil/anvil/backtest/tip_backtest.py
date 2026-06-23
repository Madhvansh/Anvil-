"""Walk-forward TIP backtest — the evidence source for the headline/watchlist gate.

For each historical trading day (look-ahead guarded via ``AsOfContext``), build the signal context,
classify+mask the regime, generate candidates, and ISSUE a tip per tradeable candidate under
``source='tip_backtest'``. Each tip is RESOLVED held-to-expiry on the realized settlement level via
``terminal_payoff`` (exact for European index options), NET of the modeled round-trip cost — so a
tip can never win on gross. Outcomes are aggregated per ``(structure, regime_bucket, underlying)``
cell and run through the shared validation battery (``backtest.aggregate.validate_cells``): calibrated
win-rate, Harvey t-stat, Deflated Sharpe across the cells tested, global PBO, robust bootstrap tail.
The per-cell verdict is written to the ``TipValidationStore`` and is the ONLY thing the gate reads.

Determinism: tip ids are content-hashed and ledger inserts are idempotent, so re-running a date
range reproduces the same curve (the bootstrap is seeded).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from ..ledger.ledger import MIN_SAMPLES_FOR_SCORE, CalibrationLedger
from ..tips.calibration import record_tip, resolve_tip
from ..tips.pipeline import tips_for_chain
from ..tips.resolve import terminal_payoff
from ..tips.store import TipValidationStore
from .aggregate import new_cell, validate_cells
from .asof import AsOfContext
from .horizon import build_day_index, robust_embargo, span_in_index


def _run_tip_days(
    day_source, day_index, unds, ledger: CalibrationLedger, store: TipValidationStore, *,
    equity: float, source: str, min_samples: int, updated_ts: str, bootstrap_seed: int,
    max_expiries: int, n_trials: int | None, issued_store,
) -> dict:
    """Shared backtest core over a ``day_source`` yielding ``(date, archive_for_that_day)``. The
    in-memory path passes the SAME full archive each day; the streaming path passes a per-day archive
    from ``iter_days`` — identical cells, because ``AsOfContext`` only ever reads its own as-of day."""
    issued_by: dict[tuple[str, str], list] = defaultdict(list)  # (underlying, expiry) -> [tip,...]
    recorded = resolved = 0
    cells: dict[tuple, dict] = defaultdict(new_cell)
    res_days: list[str] = []
    horizon_spans: list[int] = []

    for d, day_archive in day_source:
        ctx_asof = AsOfContext(d, day_archive)
        today = d.isoformat()

        # 1) Issue tips from each open, liquid chain (look-ahead guarded). Uses the SAME shared
        #    pipeline as the live paths, so the cells we measure here apply to the tips live issues.
        #    Only the NEAREST ``max_expiries`` are scored — short-term tips never use months-out
        #    expiries, and indices stack ~18 expiries/day (scoring them all is wasteful).
        for u in unds:
            chains = sorted(ctx_asof.open_chains(u), key=lambda c: c.expiry or "9999")[:max_expiries]
            for ch in chains:
                ctx, _bucket, _signals, tips = tips_for_chain(
                    ch, source=source, equity=equity, created_ts=ch.timestamp, resolve_ts=ch.expiry)
                for tip in tips:
                    record_tip(ledger, tip, spot=ctx.spot, forward=ctx.forward)
                    recorded += 1
                    issued_by[(u, ch.expiry)].append(tip)

        # 2) Resolve tips whose expiry settles exactly today, at TODAY's realized close.
        for u in unds:
            settle = ctx_asof.realized_level(u)
            if settle is None:
                continue
            for tip in issued_by.get((u, today), []):
                if tip.ledger_forecast_id is None:
                    continue
                gross = terminal_payoff(tip.legs, tip.lot_size, settle)
                net = gross - tip.round_trip_cost
                outcome = int(net > 0)
                resolve_tip(ledger, tip, outcome, resolved_ts=f"{today}T16:00:00+05:30")
                resolved += 1
                horizon_spans.append(span_in_index(tip.created_ts, today, day_index))
                cell = cells[(tip.structure, tip.regime_bucket, u)]
                ret = net / tip.max_loss if tip.max_loss > 0 else 0.0
                if issued_store is not None:  # persist resolved tip (with ret) for Gate-0 / revalidation
                    issued_store.record(tip)
                    issued_store.mark_resolved(
                        tip.tip_id, outcome, resolved_ts=f"{today}T16:00:00+05:30",
                        net_pnl=net, ret=ret)
                cell["returns"].append(ret)
                cell["net"].append(net)
                cell["conv"].append(tip.conviction)
                cell["wins"] += outcome
                cell["by_day"][today].append(ret)
                if today not in res_days:
                    res_days.append(today)

    embargo = robust_embargo(horizon_spans)  # ≥ the longest label horizon observed (leak-safe)
    reports, gpbo = validate_cells(
        cells, res_days, min_samples=min_samples, updated_ts=updated_ts,
        bootstrap_seed=bootstrap_seed, n_trials=n_trials, embargo=embargo)
    for rep in reports:
        store.upsert(rep)

    return {
        "recorded": recorded,
        "resolved": resolved,
        "cells": len(cells),
        "headline_cells": sum(1 for r in reports if r.headline_eligible),
        "global_pbo": gpbo,
        "reports": [asdict(r) for r in reports],
    }


def run_tip_backtest(
    archive, underlyings, ledger: CalibrationLedger, store: TipValidationStore, *,
    start=None, end=None, equity: float | None = None, source: str = "tip_backtest",
    min_samples: int = MIN_SAMPLES_FOR_SCORE, updated_ts: str = "", bootstrap_seed: int = 0,
    max_expiries: int = 2, n_trials: int | None = None, issued_store=None,
) -> dict:
    """In-memory walk-forward tip backtest (unchanged behavior): builds the day list from the loaded
    archive and replays each day against that same archive."""
    from ..config import SETTINGS

    unds = [u.upper() for u in underlyings]
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    days = list(archive.trading_days(start, end))
    day_index = build_day_index(dd.isoformat() for dd in days)
    day_source = ((d, archive) for d in days)
    return _run_tip_days(
        day_source, day_index, unds, ledger, store, equity=equity, source=source,
        min_samples=min_samples, updated_ts=updated_ts, bootstrap_seed=bootstrap_seed,
        max_expiries=max_expiries, n_trials=n_trials, issued_store=issued_store)


def _issue_day(args):
    """ProcessPool worker (module-level → picklable): parse ONE bhavcopy day and compute the issued tips
    (the expensive RND/GEX per-chain work). Returns ``(day_iso, [(underlying, expiry, tip, spot, forward)])``.
    PURE — opens no DuckDB handles (the ledger/store/resolution stay in the parent), so nothing unpicklable
    crosses the fork and the result is deterministic for a given day."""
    cache_dir, day_iso, unds, equity, source, max_expiries = args
    from datetime import date as _date

    from ..tips.pipeline import tips_for_chain
    from .asof import AsOfContext
    from .data import BhavcopyArchive

    d = _date.fromisoformat(day_iso)
    arch = next((a for _dd, a in BhavcopyArchive.iter_days(cache_dir, start=d, end=d)), None)
    if arch is None:
        return (day_iso, [], {})
    ctx_asof = AsOfContext(d, arch)
    out: list = []
    for u in unds:
        chains = sorted(ctx_asof.open_chains(u), key=lambda c: c.expiry or "9999")[:max_expiries]
        for ch in chains:
            ctx, _b, _s, tips = tips_for_chain(
                ch, source=source, equity=equity, created_ts=ch.timestamp, resolve_ts=ch.expiry)
            for tip in tips:
                out.append((u, ch.expiry, tip, ctx.spot, ctx.forward))
    # The day's realized close (front-future ∪ cash-close, full coverage) — for forward resolution in
    # the parent, so a partial index_close.json never caps which tips resolve.
    return (day_iso, out, dict(arch.index_close.get(day_iso, {})))


def run_tip_backtest_parallel(
    cache_dir, underlyings, ledger: CalibrationLedger, store: TipValidationStore, *,
    start=None, end=None, equity: float | None = None, source: str = "tip_backtest",
    min_samples: int = MIN_SAMPLES_FOR_SCORE, updated_ts: str = "", bootstrap_seed: int = 0,
    max_expiries: int = 2, n_trials: int | None = None, issued_store=None, workers: int = 0,
) -> dict:
    """PARALLEL streaming tip backtest (Wave 5 speed fix). The expensive per-day tip ISSUANCE (RND/GEX)
    fans out across ``workers`` processes; the stateful, cheap RESOLUTION → cell aggregation → seeded
    ``validate_cells`` stays SERIAL and in date order, so the output is byte-identical to the serial path
    (proven by the equivalence test). ``workers<=1`` runs single-process (identical to streaming)."""
    from concurrent.futures import ProcessPoolExecutor

    from ..config import SETTINGS
    from .data import BhavcopyArchive

    unds = [u.upper() for u in underlyings]
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    dates = BhavcopyArchive.cache_dates(cache_dir, start, end)
    day_index = build_day_index(dd.isoformat() for dd in dates)

    # --- Phase A: parallel tip issuance (the expensive RND/GEX) + each day's realized close, by day ---
    args = [(str(cache_dir), d.isoformat(), unds, equity, source, max_expiries) for d in dates]
    issued: dict[str, list] = {}
    realized: dict[str, dict] = {}  # day_iso -> {UND: close} (full coverage, front-future ∪ cash)
    if workers and workers > 1:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            for day_iso, day_issued, day_close in ex.map(_issue_day, args):
                issued[day_iso] = day_issued
                realized[day_iso] = day_close
    else:
        for a in args:
            day_iso, day_issued, day_close = _issue_day(a)
            issued[day_iso] = day_issued
            realized[day_iso] = day_close

    # --- Phase B: serial record + resolve + aggregate (deterministic, in date order) ---
    issued_by: dict[tuple[str, str], list] = defaultdict(list)
    recorded = resolved = 0
    cells: dict[tuple, dict] = defaultdict(new_cell)
    res_days: list[str] = []
    horizon_spans: list[int] = []
    for d in dates:
        today = d.isoformat()
        for u, expiry, tip, spot, forward in issued.get(today, []):
            record_tip(ledger, tip, spot=spot, forward=forward)
            recorded += 1
            issued_by[(u, expiry)].append(tip)
        for u in unds:
            settle = (realized.get(today, {}) or {}).get(u.upper())
            if settle is None:
                continue
            for tip in issued_by.get((u, today), []):
                if tip.ledger_forecast_id is None:
                    continue
                gross = terminal_payoff(tip.legs, tip.lot_size, float(settle))
                net = gross - tip.round_trip_cost
                outcome = int(net > 0)
                resolve_tip(ledger, tip, outcome, resolved_ts=f"{today}T16:00:00+05:30")
                resolved += 1
                horizon_spans.append(span_in_index(tip.created_ts, today, day_index))
                cell = cells[(tip.structure, tip.regime_bucket, u)]
                ret = net / tip.max_loss if tip.max_loss > 0 else 0.0
                if issued_store is not None:
                    issued_store.record(tip)
                    issued_store.mark_resolved(
                        tip.tip_id, outcome, resolved_ts=f"{today}T16:00:00+05:30", net_pnl=net, ret=ret)
                cell["returns"].append(ret)
                cell["net"].append(net)
                cell["conv"].append(tip.conviction)
                cell["wins"] += outcome
                cell["by_day"][today].append(ret)
                if today not in res_days:
                    res_days.append(today)

    embargo = robust_embargo(horizon_spans)
    reports, gpbo = validate_cells(
        cells, res_days, min_samples=min_samples, updated_ts=updated_ts,
        bootstrap_seed=bootstrap_seed, n_trials=n_trials, embargo=embargo)
    for rep in reports:
        store.upsert(rep)
    return {
        "recorded": recorded, "resolved": resolved, "cells": len(cells),
        "headline_cells": sum(1 for r in reports if r.headline_eligible),
        "global_pbo": gpbo, "reports": [asdict(r) for r in reports],
    }


def run_tip_backtest_streaming(
    cache_dir, underlyings, ledger: CalibrationLedger, store: TipValidationStore, *,
    start=None, end=None, equity: float | None = None, source: str = "tip_backtest",
    min_samples: int = MIN_SAMPLES_FOR_SCORE, updated_ts: str = "", bootstrap_seed: int = 0,
    max_expiries: int = 2, n_trials: int | None = None, issued_store=None,
) -> dict:
    """STREAMING walk-forward tip backtest (Wave 5): identical cells to ``run_tip_backtest`` but parses
    ONE bhavcopy day at a time via ``BhavcopyArchive.iter_days`` — so a windowed/full-depth cert never
    holds the whole cache in memory. The day index is read from filenames (no parse); forward expiry
    resolution rides the whole ``index_close.json`` that ``iter_days`` loads once."""
    from ..config import SETTINGS

    from .data import BhavcopyArchive

    unds = [u.upper() for u in underlyings]
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    dates = BhavcopyArchive.cache_dates(cache_dir, start, end)
    day_index = build_day_index(dd.isoformat() for dd in dates)
    day_source = BhavcopyArchive.iter_days(cache_dir, start=start, end=end)
    return _run_tip_days(
        day_source, day_index, unds, ledger, store, equity=equity, source=source,
        min_samples=min_samples, updated_ts=updated_ts, bootstrap_seed=bootstrap_seed,
        max_expiries=max_expiries, n_trials=n_trials, issued_store=issued_store)
