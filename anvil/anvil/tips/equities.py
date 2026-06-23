"""Single-stock BUY/SELL tips — the cross-sectional equities engine.

Ranks an F&O-stock universe each day by the directional factors in ``factors.equities``, takes the
strongest longs and shorts, and projects each into the SAME ``Tip`` object as the options engine (a
single linear ``EQ`` leg). So a "BUY RELIANCE, target/stop, ~58% confidence, 5d" tip flows through the
identical Tip → ledger → validation → resolve spine, with held-to-horizon resolution on the realized
cash close (``terminal_payoff`` already prices an EQ leg linearly).

Validation pools at the cross-sectional level (underlying ``"EQUITY"``) so the cell reaches sample
size — the honest claim is "the cross-sectional model has measured edge," not "this one symbol is
proven" — while per-symbol cells still accrue for granular stats. EOD-only by design: the whole path
runs on the free bhavcopy archive (cash close + futures OI), no live tick data required.
"""

from __future__ import annotations

from collections import defaultdict

from ..config import SETTINGS
from ..factors.equities import equity_signals
from ..ledger.ledger import MIN_SAMPLES_FOR_SCORE, CalibrationLedger
from ..strategy.sizing import SizingConfig, size_units
from ..strategy.types import BEARISH, BULLISH, NEUTRAL, Leg, TradeCandidate
from .build import tip_from_candidate
from .calibration import record_tip, resolve_tip
from .resolve import terminal_payoff
from .store import IssuedTipStore, TipValidationStore
from .types import HEADLINE, WATCHLIST, Tip

EQUITY_STRUCTURE = "equity_directional"
EQUITY_BUCKET = "xs_momentum"  # single cross-sectional bucket → cells pool to sample size
EQUITY_POOL = "EQUITY"  # pooled validation underlying (the model-level edge claim)

_TIER_WEIGHT = {"strong": 1.0, "confirmation": 0.4}
_STOP_PCT = 0.05
_TARGET_PCT = 0.08
_HORIZON = 5  # trading days


def _sizing() -> SizingConfig:
    return SizingConfig.from_settings()


def score_signals(signals) -> tuple[str, float]:
    """Weighted-average directional sign across active signals → (direction, score in [-1,1])."""
    num = den = 0.0
    for s in signals:
        if not s.active or not s.direction:
            continue
        w = _TIER_WEIGHT.get(s.edge_tier, 0.5) * float(s.strength)
        sign = 1.0 if s.direction == BULLISH else (-1.0 if s.direction == BEARISH else 0.0)
        num += w * sign
        den += w
    if den <= 0:
        return NEUTRAL, 0.0
    score = num / den
    if score > 0.15:
        return BULLISH, score
    if score < -0.15:
        return BEARISH, score
    return NEUTRAL, score


def edge_prob_from_score(score: float, *, cap: float | None = None) -> float:
    """Map the combined cross-sectional score to a modest, calibratable directional probability.
    Honest by construction: single-name direction clusters ~53-60%, so we cap the prior near 0.62
    (the cap is now config-backed via ``SETTINGS.equity_edge_prob_cap``; the default is unchanged)."""
    cap = SETTINGS.equity_edge_prob_cap if cap is None else cap
    return round(min(cap, 0.5 + 0.12 * min(1.0, abs(score))), 4)


def build_equity_candidate(
    symbol: str, price: float, lot_size: int, direction: str, edge_prob: float, *,
    equity: float, horizon_days: float, resolve_expiry: str,
) -> TradeCandidate:
    """One sized cash-equity directional candidate (a single linear EQ leg) with target/stop."""
    lot = int(lot_size or 1)
    bullish = direction == BULLISH
    side = "BUY" if bullish else "SELL"
    target = round(price * (1 + _TARGET_PCT) if bullish else price * (1 - _TARGET_PCT), 2)
    stop = round(price * (1 - _STOP_PCT) if bullish else price * (1 + _STOP_PCT), 2)
    ml_unit = price * _STOP_PCT * lot
    mp_unit = price * _TARGET_PCT * lot
    units, sizing_dict = size_units(ml_unit, edge_prob, mp_unit, equity, _sizing())
    units = max(1, units)
    ev_unit = edge_prob * mp_unit - (1.0 - edge_prob) * ml_unit
    leg = Leg(side=side, lots=units, expiry=resolve_expiry, ref_price=float(price),
              instrument_type="EQ", symbol=symbol)
    return TradeCandidate(
        strategy=EQUITY_STRUCTURE, underlying=symbol, direction=direction, legs=[leg], lot_size=lot,
        edge_prob=edge_prob, conviction=edge_prob,
        entry_debit_credit=round((1 if bullish else -1) * price * units * lot, 2),
        max_loss=round(ml_unit * units, 2), max_profit=round(mp_unit * units, 2), breakevens=[],
        expected_value=round(ev_unit * units, 2), horizon_days=float(horizon_days),
        entry_reason=f"cross-sectional {'long' if bullish else 'short'} (rank score)",
        invalidation_condition=f"close {'below' if bullish else 'above'} {stop}",
        target_exit=f"take profit at {target} (+{int(_TARGET_PCT*100)}%)" if bullish
        else f"take profit at {target} (-{int(_TARGET_PCT*100)}%)",
        stop_exit=f"stop at {stop}", units=units, sizing=sizing_dict,
        exit_rules={"target": target, "stop": stop}, defined_risk=True,
        rationale=f"{'BUY' if bullish else 'SELL'} {symbol}: {'momentum/long-buildup' if bullish else 'weakness/short-buildup'} ranks it in the cross-sectional {'top' if bullish else 'bottom'} of the F&O universe.",
    )


def _equity_tier(store: TipValidationStore | None, tip: Tip) -> str:
    """HEADLINE iff the POOLED equity cell is headline-eligible AND this tip clears its own costs."""
    if store is None or (tip.cost_adjusted_ev or 0) <= 0:
        return WATCHLIST
    rep = store.get(EQUITY_STRUCTURE, EQUITY_BUCKET, EQUITY_POOL)
    return HEADLINE if (rep and rep.get("headline_eligible")) else WATCHLIST


def rank_universe(archive, universe, as_of, *, top_k: int = 5):
    """Return (longs, shorts): the strongest BUY and SELL names as of ``as_of``. Each entry is
    ``(symbol, direction, score, signals, price, lot_size)``. Point-in-time (uses closes ≤ as_of)."""
    scored = []
    for sym in universe:
        series = [px for _, px in archive.equity_close_series(sym, upto=as_of)]
        if len(series) < 14:
            continue
        meta = archive.equity_meta_on(as_of, sym)
        oi = meta.get("stf_oi") if meta else None
        oichg = meta.get("stf_oi_change") if meta else None
        sigs = equity_signals(series, oi=oi, oi_change=oichg)
        direction, score = score_signals(sigs)
        if direction == NEUTRAL:
            continue
        lot = (meta or {}).get("lot_size") or 1
        scored.append((sym, direction, score, sigs, series[-1], lot))
    longs = sorted((s for s in scored if s[1] == BULLISH), key=lambda x: -x[2])[:top_k]
    shorts = sorted((s for s in scored if s[1] == BEARISH), key=lambda x: x[2])[:top_k]
    return longs, shorts


def equity_tips_as_of(archive, as_of, *, equity: float, store: TipValidationStore | None = None,
                      source: str = "tip_live", top_k: int = 5,
                      resolve_iso: str | None = None) -> list[Tip]:
    """Build (but don't persist) the ranked BUY/SELL equity tips as of ``as_of`` — the API surface."""
    longs, shorts = rank_universe(archive, universe_from_archive(archive), as_of, top_k=top_k)
    created_iso = as_of.isoformat()
    resolve = resolve_iso or created_iso  # display; the cycle sets a real forward resolve date
    out: list[Tip] = []
    for sym, direction, score, sigs, price, lot in [*longs, *shorts]:
        cand = build_equity_candidate(
            sym, price, lot, direction, edge_prob_from_score(score),
            equity=equity, horizon_days=float(_HORIZON), resolve_expiry=resolve)
        tip = tip_from_candidate(
            cand, ctx=None, signals_fired=[s.name for s in sigs if s.active], source=source,
            created_ts=f"{created_iso}T15:30:00+05:30", resolve_ts=f"{resolve}T15:30:00+05:30",
            regime_bucket=EQUITY_BUCKET)
        tip.tier = _equity_tier(store, tip)
        out.append(tip)
    return out


def universe_from_archive(archive, top_n: int | None = None) -> list[str]:
    return archive.equity_universe(top_n=top_n)


def discover_universe(cache_dir, top_n: int = 30) -> list[str]:
    """Most-liquid single-stock F&O symbols, ranked by latest-day option volume. Scans one raw CSV
    (before the archive's universe filter), so it bootstraps the universe the archive is then built
    with — keeping the archive small (only these names' rows are retained)."""
    from pathlib import Path

    from ..config import SUPPORTED_INDEXES
    from ..ingest.bhavcopy import parse_fo_bhavcopy

    csvs = sorted(Path(cache_dir).glob("*.csv"))
    if not csvs:
        return []
    rows = parse_fo_bhavcopy(csvs[-1].read_text(encoding="utf-8", errors="replace"), index_only=False)
    vol: dict[str, float] = {}
    for r in rows:
        if r.symbol in SUPPORTED_INDEXES or not r.is_option:
            continue
        vol[r.symbol] = vol.get(r.symbol, 0.0) + (r.volume or 0.0)
    return sorted(vol, key=lambda s: vol[s], reverse=True)[:top_n]


def run_equity_backtest(
    archive, universe, ledger: CalibrationLedger, store: TipValidationStore, *,
    start=None, end=None, equity: float | None = None, source: str = "tip_backtest",
    min_samples: int = MIN_SAMPLES_FOR_SCORE, horizon: int = _HORIZON, top_k: int = 5,
    updated_ts: str = "", bootstrap_seed: int = 0, n_trials: int | None = None, issued_store=None,
) -> dict:
    """Walk-forward cross-sectional backtest. Issues top/bottom names each day, resolves held-to-
    horizon on the realized cash close, aggregates per-symbol AND pooled cells, runs the battery."""
    from ..backtest.aggregate import new_cell, validate_cells

    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    days = archive.trading_days(start, end)
    cells: dict[tuple, dict] = defaultdict(new_cell)
    res_days: list[str] = []
    recorded = resolved = 0

    for i, d in enumerate(days):
        ri = i + horizon
        if ri >= len(days):
            break  # no forward close to resolve against — stop issuing
        resolve_day = days[ri]
        resolve_iso = resolve_day.isoformat()
        longs, shorts = rank_universe(archive, universe, d, top_k=top_k)
        for sym, direction, score, sigs, price, lot in [*longs, *shorts]:
            cand = build_equity_candidate(
                sym, price, lot, direction, edge_prob_from_score(score),
                equity=equity, horizon_days=float(horizon), resolve_expiry=resolve_iso)
            tip = tip_from_candidate(
                cand, ctx=None, signals_fired=[s.name for s in sigs if s.active], source=source,
                created_ts=f"{d.isoformat()}T15:30:00+05:30", resolve_ts=f"{resolve_iso}T15:30:00+05:30",
                regime_bucket=EQUITY_BUCKET)
            record_tip(ledger, tip, spot=price, forward=price)
            recorded += 1
            settle = archive.equity_close_on(resolve_day, sym)
            if settle is None:
                continue
            gross = terminal_payoff(tip.legs, tip.lot_size, settle)
            net = gross - tip.round_trip_cost
            outcome = int(net > 0)
            resolve_tip(ledger, tip, outcome, resolved_ts=f"{resolve_iso}T16:00:00+05:30")
            resolved += 1
            ret = net / tip.max_loss if tip.max_loss > 0 else 0.0
            if issued_store is not None:  # persist resolved tip (with ret) for Gate-0 / revalidation
                issued_store.record(tip)
                issued_store.mark_resolved(
                    tip.tip_id, outcome, resolved_ts=f"{resolve_iso}T16:00:00+05:30",
                    net_pnl=net, ret=ret)
            for key in ((EQUITY_STRUCTURE, EQUITY_BUCKET, sym), (EQUITY_STRUCTURE, EQUITY_BUCKET, EQUITY_POOL)):
                cell = cells[key]
                cell["returns"].append(ret)
                cell["net"].append(net)
                cell["conv"].append(tip.conviction)
                cell["wins"] += outcome
                cell["by_day"][resolve_iso].append(ret)
            if resolve_iso not in res_days:
                res_days.append(resolve_iso)

    reports, gpbo = validate_cells(
        cells, res_days, min_samples=min_samples, updated_ts=updated_ts,
        bootstrap_seed=bootstrap_seed, n_trials=n_trials, embargo=int(horizon))
    for rep in reports:
        store.upsert(rep)
    return {
        "recorded": recorded, "resolved": resolved, "cells": len(cells),
        "headline_cells": sum(1 for r in reports if r.headline_eligible),
        "pooled": next((r.__dict__ for r in reports if r.underlying == EQUITY_POOL), None),
        "global_pbo": gpbo,
    }


def run_equity_tip_cycle(
    archive, *, as_of, ledger: CalibrationLedger | None = None,
    validation_store: TipValidationStore | None = None, issued_store: IssuedTipStore | None = None,
    equity: float | None = None, top_k: int = 5, horizon: int = _HORIZON, source: str = "tip_live",
) -> dict:
    """Nightly EOD cycle: issue today's ranked BUY/SELL equity tips (persisted), and resolve any
    whose horizon has elapsed (on the realized cash close). Idempotent via content-hashed tip ids."""
    owns_led, owns_vs, owns_is = ledger is None, validation_store is None, issued_store is None
    led = ledger or CalibrationLedger()
    vstore = validation_store or TipValidationStore()
    istore = issued_store or IssuedTipStore()
    equity = equity if equity is not None else SETTINGS.paper_starting_capital
    try:
        # The forward resolve date is `horizon` trading days ahead (best-effort: next horizon days
        # in the archive, else a calendar approximation). It MUST stay in the future so freshly
        # issued tips are not treated as due-now and resolved same-day.
        from datetime import timedelta

        days = [x.isoformat() for x in archive.trading_days()]
        today = as_of.isoformat()
        future = [x for x in days if x > today]
        if len(future) >= horizon:
            resolve_iso = future[horizon - 1]
        else:
            resolve_iso = (as_of + timedelta(days=max(1, horizon) * 2)).isoformat()
        tips = equity_tips_as_of(archive, as_of, equity=equity, store=vstore, source=source,
                                 top_k=top_k, resolve_iso=resolve_iso)
        for tip in tips:
            record_tip(led, tip, spot=tip.legs[0]["ref_price"], forward=tip.legs[0]["ref_price"])
            istore.record(tip)

        # Resolve due equity tips (resolve_ts on/before as_of) at each name's realized cash close.
        resolved = 0
        due = _due_equity_tips(istore, today)
        for d in due:
            sym = d["underlying"]
            settle = archive.equity_close_on(_as_date(today), sym)
            if settle is None:
                continue
            gross = terminal_payoff(d["legs"], int(d["lot_size"]), float(settle))
            net = gross - float(d["round_trip_cost"])
            outcome = int(net > 0)
            ml = float(d.get("max_loss") or 0.0)
            ret = net / ml if ml > 0 else 0.0
            fid = d.get("ledger_forecast_id")
            if fid:
                try:
                    led.resolve(fid, 1.0 if outcome else -1.0, resolved_ts=f"{today}T16:00:00+05:30")
                except KeyError:
                    pass
            istore.mark_resolved(d["tip_id"], outcome, f"{today}T16:00:00+05:30", net_pnl=net, ret=ret)
            resolved += 1
        return {"source": source, "issued": len(tips), "resolved": resolved,
                "buys": sum(1 for t in tips if t.direction == BULLISH),
                "sells": sum(1 for t in tips if t.direction == BEARISH)}
    finally:
        if owns_led:
            led.close()
        if owns_vs:
            vstore.close()
        if owns_is:
            istore.close()


def _as_date(iso: str):
    from datetime import date
    return date.fromisoformat(iso[:10])


def _due_equity_tips(istore: IssuedTipStore, as_of_date: str) -> list[dict]:
    """Unresolved EQUITY tips (structure=equity_directional) whose resolve date has elapsed."""
    rows = istore.con.execute(
        "SELECT tip_id, ledger_forecast_id, underlying, lot_size, round_trip_cost, max_loss, legs, resolve_ts "
        "FROM tips_issued WHERE structure=? AND resolved=FALSE AND substr(resolve_ts,1,10) <= ?",
        [EQUITY_STRUCTURE, as_of_date[:10]],
    ).fetchall()
    cols = ["tip_id", "ledger_forecast_id", "underlying", "lot_size", "round_trip_cost", "max_loss", "legs", "resolve_ts"]
    out = []
    import json
    for r in rows:
        rec = dict(zip(cols, r))
        rec["legs"] = json.loads(rec["legs"]) if isinstance(rec["legs"], str) else rec["legs"]
        out.append(rec)
    return out
